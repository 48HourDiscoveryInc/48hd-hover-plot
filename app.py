import math
import polars as pl

import io
import base64
import plotly.express as px

from dash import Dash
from dash import dash_table
from dash import dcc, html
from dash import callback
from dash import Input, Output, State

import dash_daq as daq

app = Dash(__name__)
server = app.server

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

    dcc.Loading(id='loading-manhattan', type='default', children=[
        dcc.Graph(id='manhattan-plot'),
    ], color='black', overlay_style=OVERLAY_STYLE_2),

    dash_table.DataTable(id='selection-data', page_action='none', export_format='xlsx', style_table=TABLE_STYLE)
])

@callback(
    Output('data-store', 'data'),
    Output('upload-data', 'children'),
    Output('column-dropdown', 'options'),
    Output('column-dropdown', 'value'),
    Output('sequence-dropdown', 'options'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
def upload_data(contents, filename):
    if contents is None:
        return [], 'Upload A CSV/XLSX', [], None, []
    
    _, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    if filename.endswith('.csv') or filename.endswith('.xlsx'):

        print('loading data')
        if filename.endswith('.csv'):
            load_data = pl.read_csv(io.StringIO(decoded.decode('utf-8')), null_values=['#DIV/0!'])
        elif filename.endswith('.xlsx'):
            load_data = pl.read_excel(io.BytesIO(decoded))

        # check for required columns
        required_columns = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']
        available_columns = load_data.collect_schema()
        for column in required_columns:
            if not column in available_columns:
                return [], html.Label(f'{filename} does not have column: {column}', style=ERROR_STYLE), [], None, []
            
        # check for FC columns
        fc_columns = [col for col in available_columns if 'FC' in col]
        if len(fc_columns) == 0:
            return [], html.Label(f'{filename} does not have FC columns', style=ERROR_STYLE), [], None, []

        # transform data
        group_counts = load_data.group_by('GroupID').agg(pl.count('GroupID').alias('count'))

        load_data = load_data.select(required_columns + fc_columns) \
            .sort(['seq_origin', 'GroupID', 'Position']) \
            .join(group_counts, on='GroupID', how='left') \
            .with_columns(pl.lit('parent').alias('add_parent')) \
            .with_columns(pl.when((pl.col('count') > 1) & (pl.col('Position') == '0Z')).then('add_parent').otherwise('seq_origin').alias('Legend')) \
            .select(required_columns + fc_columns + ['Legend']) \
            .with_row_index()

        sequences = sorted(load_data['sequence'].unique())
        store_data = load_data.to_pandas().to_dict('records')
        print('loaded data')

        return store_data, f'📄 {filename}', fc_columns, fc_columns[0], sequences
    
    return [], html.Label(f'Error reading {filename}', style=ERROR_STYLE), [], None, []

@callback(
    Output('manhattan-plot', 'figure'),
    Output('sequence-dropdown', 'value'),
    Output('manhattan-plot', 'clickData'),
    Output('selection-data', 'data'),
    State('data-store', 'data'),
    Input('column-dropdown', 'value'),
    Input('scale-dropdown', 'value'),
    Input('sequence-dropdown', 'value'),
    Input('manhattan-plot', 'clickData'),
    Input('manhattan-plot', 'selectedData'),
    Input('boolean-switch', 'on'),
    Input('page-dropdown', 'value'),
    prevent_initial_call=True
)
def update_graph(store_data, y_columns, scale, selected, click_data, selected_data, erase, pages):

    if not store_data or not y_columns:
        print('no data')
        return {}, None, None, []

    plot_data = pl.from_records(store_data)
    
    if type(y_columns) == str:
        y_columns = [y_columns]

    if click_data is None:
        pass
    else:
        selection = click_data['points'][0]['customdata'][4]
        if erase:
            if selected is not None:
                selected = [x for x in selected if x != selection]
        else:
            if selected is None:
                selected = [selection]
            elif not selection in selected:
                selected += [selection]

    if selected_data is None:
        pass
    else:
        selections = [point['customdata'][4] for point in selected_data['points']]
        if erase:
            if selected is not None:
                selected = [x for x in selected if not x in selections]
        else:
            if selected is None:
                selected = selections
            else:
                selected += [x for x in selections if not x in selected]

    # select sequences
    required_columns = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']
    if selected is not None:
        # add selections to legend
        plot_data = plot_data.with_columns(pl.lit('selection').alias('add_selection')) \
            .with_columns(pl.when(pl.col('sequence').is_in(selected)).then('add_selection').otherwise('Legend').alias('Legend'))

        # selection data for export
        selection_data = plot_data.filter(pl.col('Legend') == 'selection') \
            .select(required_columns + [col for col in plot_data.collect_schema() if 'FC' in col]) \
            .to_pandas().to_dict('records')

    else:
        selection_data = []

    # select scale
    if scale == 'Square Root':
        plot_column = 'FC (sqrt)'
        plot_data = pl.concat([
            plot_data.with_columns(pl.col(y_column).sqrt().alias(plot_column)) \
                .with_columns(pl.lit(y_column).alias('Target')) \
                .select(['index'] + required_columns + [plot_column, 'Legend', 'Target'])
        for y_column in y_columns])

    elif scale == 'Log10':
        plot_column = 'FC (log10)'
        plot_data = pl.concat([
            plot_data.with_columns(pl.col(y_column).log10().alias(plot_column)) \
                .with_columns(pl.lit(y_column).alias('Target')) \
                .select(['index'] + required_columns + [plot_column, 'Legend', 'Target']) \
        for y_column in y_columns])
    else:
        plot_column = 'FC'
        plot_data = pl.concat([
            plot_data.with_columns(pl.col(y_column).alias(plot_column)) \
                .with_columns(pl.lit(y_column).alias('Target')) \
                .select(['index'] + required_columns + [plot_column, 'Legend', 'Target'])
        for y_column in y_columns])

    # improve dtypes
    dtypes = {
        col: (pl.Categorical if col in ['Position', 'seq_origin', 'sequence', 'Legend', 'Target'] else
            pl.Int32 if col in ['index', 'Input_CPM'] else
            pl.Float32 if 'FC' in col else
            pl.Utf8)
        for col in plot_data.collect_schema().names()
    }

    plot_data = plot_data.with_columns([pl.col(col).cast(dtypes[col]).alias(col)for col in plot_data.collect_schema().names()]) \
        .with_columns((pl.col('Legend') == 'parent').cast(pl.Int8).alias('is_parent')) \
        .with_columns((pl.col('Legend') == 'selection').cast(pl.Int8).alias('is_selection')) \
        .sort(['is_selection', 'is_parent', 'Legend']) \
        .select([col for col in plot_data.collect_schema().names()])

    height = 100
    n_plots = len(y_columns)
    height += math.ceil(n_plots / pages) * 300
    hover_data = {'Legend': False, 'seq_origin': True, 'GroupID': True, 'Position': True, 'sequence': True, 'Input_CPM': True}
    fig = px.scatter(plot_data, x='index', y=plot_column, color='Legend', facet_col='Target', facet_col_wrap=pages, hover_name='Legend', hover_data=hover_data, height=height)

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

    return fig, selected, None, selection_data

if __name__ == '__main__':
    app.run(debug=True)