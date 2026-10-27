import io
import os
import re
import math
import uuid
import html as html_lib
import base64
import logging
import zipfile

import polars as pl
import plotly.express as px

from dash import Dash
from dash import dash_table
from dash import dcc, html
from dash import callback
from dash import Input, Output, State

import dash_daq as daq
from flask_caching import Cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Dash(__name__)
server = app.server

# processed data lives server-side (shared by all gunicorn workers on the instance),
# the browser only keeps a key to it
cache = Cache(server, config={
    'CACHE_TYPE': 'FileSystemCache',
    'CACHE_DIR': os.environ.get('CACHE_DIR', 'cache'),
    'CACHE_DEFAULT_TIMEOUT': 6 * 60 * 60,
    'CACHE_THRESHOLD': 50,
})

BASE_COLUMNS = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']

FONT_STYLE = {'fontFamily': 'monospace'}
UPLOAD_STYLE = {
    'height': '60px',
    'lineHeight': '60px',
    'borderWidth': '2px',
    'borderStyle': 'dashed',
    'borderRadius': '8px',
    'borderColor': 'lightgray',
    'textAlign': 'center',
    'margin': '10px',
    **FONT_STYLE
}
LABEL_STYLE = {
    'fontWeight': 'bold',
    **FONT_STYLE
}
DROPDOWN_STYLE = {
    **FONT_STYLE
}
TABLE_STYLE = {
    'height': '300px',
    'overflowY': 'auto'
}
OVERLAY_STYLE_1 = {
    'visibility': 'visible',
    'opacity': '0.0',
}
OVERLAY_STYLE_2 = {
    'visibility': 'visible',
    'opacity': '0.3',
}
ERROR_STYLE = {
    'color': 'red',
    **FONT_STYLE
}
SDB_SHOW_STYLE = {'margin': '10px', 'width': '200px'}
SDB_HIDE_STYLE = {'display': 'none'}

app.layout = html.Div([

    html.H3('48Hour Discovery Inc.', style=FONT_STYLE),
    dcc.Store(id='data-store'),

    dcc.Loading(id='loading-upload', type='default', children=[
        dcc.Upload(id='upload-data', children='Upload A CSV/XLSX', style=UPLOAD_STYLE),
    ], color='black', overlay_style=OVERLAY_STYLE_1),

    html.Div([
        html.Div([
            html.Label('Select column', style=LABEL_STYLE),
            dcc.Dropdown(id='column-dropdown', multi=True, style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '250px'}),

        html.Div([
            html.Label('Y-axis scale', style=LABEL_STYLE),
            dcc.Dropdown(id='scale-dropdown', options=['Linear', 'Square Root', 'Log10'], value='Log10', style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '150px'}),

        html.Div([
            html.Label('SDB', style=LABEL_STYLE),
            dcc.Dropdown(id='sdb-dropdown', multi=True, style=DROPDOWN_STYLE),
        ], id='sdb-container', style=SDB_HIDE_STYLE),

        html.Div([
            html.Label('Select sequences', style=LABEL_STYLE),
            dcc.Dropdown(id='sequence-dropdown', style=DROPDOWN_STYLE, multi=True, persistence=True, persistence_type='local'),
        ], style={'flex': '1', 'margin': '10px'}),

        html.Div([
            html.Label('Erase', style=LABEL_STYLE, id='switch-message'),
            daq.BooleanSwitch(id='boolean-switch', on=False, color='gray'),
        ], style={'margin': '10px'}),

        html.Div([
            html.Label('Pages', style=LABEL_STYLE),
            dcc.Dropdown(id='page-dropdown', options=[1, 2, 3], value=2, style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '100px'}),
    ], style={'display': 'flex', 'flexDirection': 'row', 'gap': '10px'}),

    html.Div(id='plot-message'),

    dcc.Loading(id='loading-manhattan', type='default', children=[
        dcc.Graph(id='manhattan-plot'),
    ], color='black', overlay_style=OVERLAY_STYLE_2),

    dash_table.DataTable(id='selection-data', page_action='none', export_format='xlsx', style_table=TABLE_STYLE)
])


def is_fc(name):
    return name.startswith('FC')


def is_cpm(name):
    return name.endswith('CPM') and name not in BASE_COLUMNS


def is_wanted(name):
    # numeric columns: only FC* and *CPM are needed
    return name in BASE_COLUMNS or name == 'SDB' or is_fc(name) or is_cpm(name)


ROW_RE = re.compile(r'<row\b[^>]*?(?:/>|>(.*?)</row>)', re.S)
CELL_RE = re.compile(r'<c r="([A-Z]+)\d+"([^>]*?)(?:/>|>(.*?)</c>)', re.S)
VALUE_RE = re.compile(r'<v>(.*?)</v>', re.S)
TEXT_RE = re.compile(r'<t\b[^>]*?(?:/>|>(.*?)</t>)', re.S)
SI_RE = re.compile(r'<si>(.*?)</si>', re.S)


def xml_text(text):
    return html_lib.unescape(text) if '&' in text else text


def first_sheet_path(archive):
    workbook = archive.read('xl/workbook.xml').decode('utf-8')
    rels = archive.read('xl/_rels/workbook.xml.rels').decode('utf-8')
    sheet_id = re.search(r'<sheet\b[^>]*?r:id="([^"]+)"', workbook).group(1)
    for rel in re.findall(r'<Relationship\b[^>]*>', rels):
        if f'Id="{sheet_id}"' in rel:
            target = re.search(r'Target="([^"]+)"', rel).group(1)
            return target.lstrip('/') if target.startswith('/') else 'xl/' + target
    return 'xl/worksheets/sheet1.xml'


def cell_value(attrs, inner, shared_strings):
    if inner is None:
        return None
    if 't="inlineStr"' in attrs:
        return xml_text(''.join(t or '' for t in TEXT_RE.findall(inner)))
    match = VALUE_RE.search(inner)
    if match is None or 't="e"' in attrs:
        return None
    if 't="s"' in attrs:
        return shared_strings[int(match.group(1))]
    return xml_text(match.group(1))


def iter_xlsx_rows(stream, chunk_size=4 * 2**20):
    """Yield the inner XML of each <row> without holding the whole sheet in memory."""
    buffer = ''
    while True:
        chunk = stream.read(chunk_size)
        buffer += chunk
        end = buffer.rfind('</row>') + len('</row>') if chunk else len(buffer)
        yield from (row or '' for row in ROW_RE.findall(buffer, 0, end))
        buffer = buffer[end:]
        if not chunk:
            break


def read_xlsx(decoded):
    """Stream the first sheet, keeping only the wanted columns; for GS files (with SDB)
    Input_CPM == 0 rows are dropped while streaming.

    calamine/openpyxl load every cell and need >1 GB for the full GS file (491 MB of
    sheet XML), which gets the worker killed on a 512 MB Render instance.
    """
    with zipfile.ZipFile(io.BytesIO(decoded)) as archive:
        shared_strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            text = archive.read('xl/sharedStrings.xml').decode('utf-8')
            shared_strings = [xml_text(''.join(t or '' for t in TEXT_RE.findall(si))) for si in SI_RE.findall(text)]
            del text

        with archive.open(first_sheet_path(archive)) as raw:
            rows = iter_xlsx_rows(io.TextIOWrapper(raw, encoding='utf-8'))
            header = {letter: cell_value(attrs, inner, shared_strings) for letter, attrs, inner in CELL_RE.findall(next(rows, ''))}
            available_columns = [name for name in header.values() if name is not None]
            letters = {letter: name for letter, name in header.items() if name is not None and is_wanted(name)}
            if not all(column in available_columns for column in BASE_COLUMNS):
                return pl.DataFrame(), available_columns

            has_sdb = 'SDB' in available_columns
            letter_of = {name: letter for letter, name in letters.items()}
            cpm_letter, group_letter = letter_of['Input_CPM'], letter_of['GroupID']
            # only match cells in the wanted columns, the GS file has ~60 unused count columns
            wanted_re = re.compile(r'<c r="(' + '|'.join(letters) + r')\d+"([^>]*?)(?:/>|>(.*?)</c>)', re.S)

            # group sizes are counted over all rows, before filtering, so scan parents stay marked
            group_sizes = {}
            columns = {name: [] for name in letters.values()}
            for row in rows:
                cells = {letter: (attrs, inner) for letter, attrs, inner in wanted_re.findall(row)}
                group = cell_value(*cells.get(group_letter, ('', None)), shared_strings)
                group_sizes[group] = group_sizes.get(group, 0) + 1
                if has_sdb:
                    cpm = cell_value(*cells.get(cpm_letter, ('', None)), shared_strings)
                    if cpm is None or float(cpm) == 0:
                        continue
                for letter, name in letters.items():
                    columns[name].append(cell_value(*cells.get(letter, ('', None)), shared_strings))

    columns['count'] = [group_sizes[group] for group in columns['GroupID']]
    return pl.DataFrame(columns, schema={name: pl.Utf8 if name != 'count' else pl.UInt32 for name in columns}), available_columns


def load_dataframe(decoded, filename):
    """Read an uploaded GS (has SDB) or R3 (no SDB) file.

    Returns (data, fc_columns, cpm_columns, has_sdb) or raises ValueError with a user-facing message.
    """
    if filename.endswith('.xlsx'):
        data, available_columns = read_xlsx(decoded)
    elif filename.endswith('.csv'):
        available_columns = pl.read_csv(io.BytesIO(decoded), n_rows=0).columns
        data = pl.read_csv(io.BytesIO(decoded), columns=[col for col in available_columns if is_wanted(col)], null_values=['#DIV/0!'])
    else:
        raise ValueError(f'Error reading {filename}')

    # check for required columns
    for column in BASE_COLUMNS:
        if column not in available_columns:
            raise ValueError(f'{filename} does not have column: {column}')

    # check for FC columns
    fc_columns = [col for col in available_columns if is_fc(col)]
    if len(fc_columns) == 0:
        raise ValueError(f'{filename} does not have FC columns')

    cpm_columns = [col for col in available_columns if is_cpm(col)]
    has_sdb = 'SDB' in available_columns
    key_columns = BASE_COLUMNS + (['SDB'] if has_sdb else [])

    # transform data, group sizes are counted before filtering so scan parents stay marked
    # (the xlsx reader already counted them and dropped the zero Input_CPM rows)
    if 'count' not in data.columns:
        data = data.with_columns(pl.len().over('GroupID').alias('count'))
    data = data.select(key_columns + cpm_columns + fc_columns + ['count']) \
        .with_columns(
            pl.col('GroupID').cast(pl.Float64).cast(pl.Int64),
            pl.col(['Input_CPM'] + cpm_columns).cast(pl.Float64).cast(pl.Int32),
            pl.col(fc_columns).cast(pl.Float32),
        )

    # GS only: drop sequences that were not seen in the input
    if has_sdb:
        data = data.filter(pl.col('Input_CPM') != 0)

    data = data.sort(['seq_origin', 'GroupID', 'Position']) \
        .with_columns(pl.when((pl.col('count') > 1) & (pl.col('Position') == '0Z')).then(pl.lit('parent')).otherwise(pl.col('seq_origin')).alias('Legend')) \
        .select(key_columns + cpm_columns + fc_columns + ['Legend']) \
        .with_row_index()

    return data, fc_columns, cpm_columns, has_sdb


def upload_error(message):
    return None, html.Label(message, style=ERROR_STYLE), [], None, [], [], None, SDB_HIDE_STYLE


@callback(
    Output('data-store', 'data'),
    Output('upload-data', 'children'),
    Output('column-dropdown', 'options'),
    Output('column-dropdown', 'value'),
    Output('sequence-dropdown', 'options'),
    Output('sdb-dropdown', 'options'),
    Output('sdb-dropdown', 'value'),
    Output('sdb-container', 'style'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
def upload_data(contents, filename):
    if contents is None:
        return None, 'Upload A CSV/XLSX', [], None, [], [], None, SDB_HIDE_STYLE

    logger.info('loading %s', filename)
    try:
        decoded = base64.b64decode(contents.split(',', 1)[1])
        load_data, fc_columns, cpm_columns, has_sdb = load_dataframe(decoded, filename)
    except ValueError as e:
        return upload_error(str(e))
    except Exception:
        logger.exception('failed to read %s', filename)
        return upload_error(f'Error reading {filename}')
    del decoded

    buffer = io.BytesIO()
    load_data.write_parquet(buffer)
    key = uuid.uuid4().hex
    cache.set(key, buffer.getvalue())

    sequences = load_data['sequence'].unique().sort().to_list()
    sdbs = load_data['SDB'].unique().sort().to_list() if has_sdb else []
    logger.info('loaded %s: %d rows', filename, load_data.height)

    store_data = {'key': key, 'has_sdb': has_sdb, 'fc_columns': fc_columns, 'cpm_columns': cpm_columns}
    return store_data, f'📄 {filename}', fc_columns, fc_columns[0], sequences, sdbs, sdbs, SDB_SHOW_STYLE if has_sdb else SDB_HIDE_STYLE


@callback(
    Output('manhattan-plot', 'figure'),
    Output('sequence-dropdown', 'value'),
    Output('manhattan-plot', 'clickData'),
    Output('selection-data', 'data'),
    Output('plot-message', 'children'),
    State('data-store', 'data'),
    Input('column-dropdown', 'value'),
    Input('scale-dropdown', 'value'),
    Input('sequence-dropdown', 'value'),
    Input('manhattan-plot', 'clickData'),
    Input('manhattan-plot', 'selectedData'),
    Input('boolean-switch', 'on'),
    Input('page-dropdown', 'value'),
    Input('sdb-dropdown', 'value'),
    prevent_initial_call=True
)
def update_graph(store_data, y_columns, scale, selected, click_data, selected_data, erase, pages, sdbs):

    if not store_data or not y_columns:
        return {}, None, None, [], None

    cached = cache.get(store_data['key'])
    if cached is None:
        return {}, selected, None, [], html.Label('Data expired, please upload the file again', style=ERROR_STYLE)

    plot_data = pl.read_parquet(io.BytesIO(cached))
    key_columns = BASE_COLUMNS + (['SDB'] if store_data['has_sdb'] else [])

    if store_data['has_sdb'] and sdbs:
        plot_data = plot_data.filter(pl.col('SDB').is_in(sdbs))

    if type(y_columns) == str:
        y_columns = [y_columns]

    # customdata[0] is the sequence (see custom_data in px.scatter)
    if click_data is not None:
        selection = click_data['points'][0]['customdata'][0]
        if erase:
            if selected is not None:
                selected = [x for x in selected if x != selection]
        else:
            if selected is None:
                selected = [selection]
            elif not selection in selected:
                selected += [selection]

    if selected_data is not None:
        selections = [point['customdata'][0] for point in selected_data['points']]
        if erase:
            if selected is not None:
                selected = [x for x in selected if not x in selections]
        else:
            if selected is None:
                selected = selections
            else:
                selected += [x for x in selections if not x in selected]

    # select sequences
    if selected:
        # add selections to legend
        plot_data = plot_data.with_columns(pl.when(pl.col('sequence').is_in(selected)).then(pl.lit('selection')).otherwise(pl.col('Legend')).alias('Legend'))

        # selection data for export
        selection_data = plot_data.filter(pl.col('Legend') == 'selection') \
            .select(key_columns + store_data['cpm_columns'] + store_data['fc_columns']) \
            .to_dicts()
    else:
        selection_data = []

    # select scale
    if scale == 'Square Root':
        plot_column = 'FC (sqrt)'
        y_expr = pl.col(plot_column).sqrt()
    elif scale == 'Log10':
        plot_column = 'FC (log10)'
        y_expr = pl.col(plot_column).log10()
    else:
        plot_column = 'FC'
        y_expr = pl.col(plot_column)

    plot_data = plot_data.unpivot(on=y_columns, index=['index'] + key_columns + ['Legend'], variable_name='Target', value_name=plot_column) \
        .with_columns(y_expr) \
        .filter(pl.col(plot_column).is_finite()) \
        .with_columns(
            pl.col(['Position', 'seq_origin', 'Legend', 'Target'] + (['SDB'] if store_data['has_sdb'] else [])).cast(pl.Categorical),
            pl.col('index').cast(pl.Int32),
            (pl.col('Legend') == 'parent').cast(pl.Int8).alias('is_parent'),
            (pl.col('Legend') == 'selection').cast(pl.Int8).alias('is_selection'),
        ) \
        .sort(['is_selection', 'is_parent', 'Legend']) \
        .drop(['is_selection', 'is_parent'])

    height = 100
    n_plots = len(y_columns)
    height += math.ceil(n_plots / pages) * 350
    hover_data = {'Legend': False, 'sequence': True, 'seq_origin': True, 'GroupID': True, 'Position': True}
    if store_data['has_sdb']:
        hover_data['SDB'] = True
    hover_data['Input_CPM'] = True
    fig = px.scatter(plot_data, x='index', y=plot_column, color='Legend', facet_col='Target', facet_col_wrap=pages,
                     hover_name='Legend', hover_data=hover_data, custom_data=['sequence'], height=height, render_mode='webgl')

    # color parents and selection
    for trace in fig.data:
        if trace.name == 'parent':
            trace.marker.color = 'black'
            trace.marker.size = 4.5
        elif trace.name == 'selection':
            trace.marker.color = 'red'
            trace.marker.line = {'color': 'black', 'width': 2}
            trace.marker.size = 7.5
        else:
            trace.marker.size = 4.5

    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=True)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=True)

    fig.update_layout(template='plotly_white')

    return fig, selected, None, selection_data, None

if __name__ == '__main__':
    app.run(debug=os.environ.get('DASH_DEBUG') == '1')
