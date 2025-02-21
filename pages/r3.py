import math
import polars as pl

import io
import base64
import plotly.express as px

import dash
from dash import Dash
from dash import dash_table
from dash import dcc, html
from dash import callback
from dash import Input, Output, State

import dash_daq as daq

# app = Dash(__name__)
# server = app.server

dash.register_page(__name__)

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

layout = html.Div([

    # html.H3('48Hour Discovery Inc.', style=FONT_STYLE),
    dcc.Store(id='data-store-r3'),

    dcc.Loading(id='loading-upload-r3', type='default', children=[
        dcc.Upload(id='upload-data-r3', children='Upload A CSV/XLSX for R3', style=UPLOAD_STYLE),
    ], color='black', overlay_style=OVERLAY_STYLE_1),

    html.Div([
        html.Div([
            html.Label('Select column', style=LABEL_STYLE),
            dcc.Dropdown(id='column-dropdown-r3', multi=False, style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '250px'}),

        html.Div([
            html.Label('Y-axis scale', style=LABEL_STYLE),
            dcc.Dropdown(id='scale-dropdown-r3', options=['Linear', 'Square Root', 'Log10'], value='Log10', style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '150px'}),

        html.Div([
            html.Label('Select sequences', style=LABEL_STYLE),
            dcc.Dropdown(id='sequence-dropdown-r3', style=DROPDOWN_STYLE, multi=True, persistence=True, persistence_type='local'),
        ], style={'flex': '1', 'margin': '10px'}),

        html.Div([
            html.Label('Erase', style=LABEL_STYLE, id='switch-message'),
            daq.BooleanSwitch(id='boolean-switch-r3', on=False, color='gray'),
        ], style={'margin': '10px'}),
    ], style={'display': 'flex', 'flexDirection': 'row', 'gap': '10px'}),

    dcc.Loading(id='loading-manhattan', type='default', children=[
        dcc.Graph(id='manhattan-plot-r3'),
    ], color='black', overlay_style=OVERLAY_STYLE_2),

    dash_table.DataTable(id='selection-data-r3', page_action='none', export_format='xlsx', style_table=TABLE_STYLE)
])

@callback(
    Output('data-store-r3', 'data'),
    Output('upload-data-r3', 'children'),
    Output('column-dropdown-r3', 'options'),
    Output('column-dropdown-r3', 'value'),
    Output('sequence-dropdown-r3', 'options'),
    Input('upload-data-r3', 'contents'),
    State('upload-data-r3', 'filename'),
    prevent_initial_call=True
)
def upload_data(contents, filename):
    if contents is None:
        return [], 'Upload A CSV/XLSX for R3', [], None, []
    
    _, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    if filename.endswith('.csv') or filename.endswith('.xlsx'):

        print('loading data')
        if filename.endswith('.csv'):
            load_data = pl.read_csv(io.StringIO(decoded.decode('utf-8')), null_values=['#DIV/0!'])
        elif filename.endswith('.xlsx'):
            load_data = pl.read_excel(io.BytesIO(decoded))

        # check for required columns
        required_columns = ['GroupID', 'Position', 'seq_origin', 'sequence']
        available_columns = load_data.collect_schema()
        for column in required_columns:
            if not column in available_columns:
                return [], html.Label(f'{filename} does not have column: {column}', style=ERROR_STYLE), [], None, []
            
        # check for FC columns
        cpm_columns = [col for col in available_columns if 'CPM' in col]
        fc_columns = [col for col in available_columns if 'FC' in col]
        if len(fc_columns) == 0:
            return [], html.Label(f'{filename} does not have FC columns', style=ERROR_STYLE), [], None, []

        load_data = load_data.select(required_columns + cpm_columns + fc_columns) \
            .with_columns(pl.col('seq_origin').alias('Legend')) \
            .select(required_columns + cpm_columns + fc_columns + ['Legend'])

        sequences = sorted(load_data['sequence'].unique())
        store_data = load_data.to_pandas().to_dict('records')
        print('loaded data')

        return store_data, f'📄 {filename}', fc_columns, fc_columns[0], sequences
    
    return [], html.Label(f'Error reading {filename}', style=ERROR_STYLE), [], None, []

@callback(
    Output('manhattan-plot-r3', 'figure'),
    Output('sequence-dropdown-r3', 'value'),
    Output('manhattan-plot-r3', 'clickData'),
    Output('selection-data-r3', 'data'),
    State('data-store-r3', 'data'),
    Input('column-dropdown-r3', 'value'),
    Input('scale-dropdown-r3', 'value'),
    Input('sequence-dropdown-r3', 'value'),
    Input('manhattan-plot-r3', 'clickData'),
    Input('manhattan-plot-r3', 'selectedData'),
    Input('boolean-switch-r3', 'on'),
    prevent_initial_call=True
)
def update_graph(store_data, y_column, scale, selected, click_data, selected_data, erase):

    if not store_data or not y_column:
        print('no data')
        return {}, None, None, []
    
    cpm_column = y_column.split('.')[1] + '_CPM'

    plot_data = pl.from_records(store_data)

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
    required_columns = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM', cpm_column]
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
        plot_data = plot_data.with_columns(pl.col(y_column).sqrt()) \
            .with_columns(pl.lit(y_column).alias('Target')) \
            .select(required_columns + [y_column, 'Legend', 'Target'])

    elif scale == 'Log10':
        plot_data = plot_data.with_columns(pl.col(y_column).log10()) \
            .with_columns(pl.lit(y_column).alias('Target')) \
            .select(required_columns + [y_column, 'Legend', 'Target'])
    else:
        plot_data = plot_data.with_columns(pl.col(y_column)) \
            .with_columns(pl.lit(y_column).alias('Target')) \
            .select(required_columns + [y_column, 'Legend', 'Target'])

    # improve dtypes
    dtypes = {
        col: (pl.Categorical if col in ['Position', 'seq_origin', 'sequence', 'Legend', 'Target'] else
            pl.Int32 if col in ['index', 'Input_CPM', cpm_column] else
            pl.Float32 if 'FC' in col else
            pl.Utf8)
        for col in plot_data.collect_schema().names()
    }

    plot_data = plot_data.with_columns([pl.col(col).cast(dtypes[col]).alias(col)for col in plot_data.collect_schema().names()]) \
        .with_columns((pl.col('Legend') == 'selection').cast(pl.Int8).alias('is_selection')) \
        .sort(['is_selection', 'Legend']) \
        .select([col for col in plot_data.collect_schema().names()])
    
    seq_origin_data_list = []
    for seq_origin in sorted(plot_data['seq_origin'].unique().to_list()):
        seq_origin_data = plot_data.filter(pl.col('seq_origin') == seq_origin) \
            .sort(f'Input_CPM', descending=True) \
            .with_row_index()
        seq_origin_data_list.append(seq_origin_data)
    plot_data = pl.concat(seq_origin_data_list)

    hover_data = {'Legend': False, 'seq_origin': True, 'GroupID': True, 'Position': True, 'sequence': True, 'Input_CPM': True, cpm_column: True}
    fig = px.scatter(plot_data, x='index', y=y_column, color='Legend', facet_col='seq_origin', hover_name='Legend', log_x=True, hover_data=hover_data, height=500)

    for annotations in fig.layout.annotations:
        annotations['text'] = annotations['text'].split('=')[-1].split('-')[-1]

    control_seq_origin = 'Ref'
    for seq_origin in plot_data['seq_origin'].unique():
        if seq_origin.startswith('GS'):
            control_seq_origin = seq_origin

    for trace in fig.data:
        trace.marker.size = 4.5
        if trace.name == 'unmapped':
            trace.marker.color = 'lightgray'
        elif trace.name == control_seq_origin:
            trace.marker.color = 'gray'
        elif trace.name == 'selection':
            trace.marker.size = 7.5
            trace.marker.color = 'red'
            trace.marker.line = {'color': 'black', 'width': 2}
        else:
            color = trace['marker']['color']
            top_enriched = sorted(trace['y'])[-200:]
            top_abundant = sorted(trace['customdata'][:, 6])[-200:]
            trace['marker']['color'] = ['chocolate' if i in top_abundant else color for i in trace['customdata'][:, 6]]
            trace['marker']['color'] = ['gold' if y in top_enriched else color for y, color in zip(trace['y'], trace['marker']['color'])]

    fig.update_xaxes(matches=None, title=None, tickmode='linear', tickangle=90, exponentformat='power', tickfont=dict(size=10))

    shapes = [
        dict(type='rect', xref='paper', yref='paper', x0=0, y0=0, x1=1.0, y1=1.0, line=dict(color='black', width=1))
    ]

    fig.update_layout(template='plotly_white', showlegend=False, shapes=shapes)

    return fig, selected, None, selection_data

# if __name__ == '__main__':
#     app.run(debug=True)