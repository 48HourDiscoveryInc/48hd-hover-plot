import math
import numpy as np
import pandas as pd

import io
import base64
import pickle
import plotly.express as px

from dash import Dash
from dash import dash_table
from dash import dcc, html
from dash import callback
from dash import Input, Output, State
from dash import Patch

from flask_caching import Cache

app = Dash(__name__)

server = app.server

cache = Cache(server, config={
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': 'cache'
})

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

    dcc.Loading(id='loading-upload', type='default', children=[
        dcc.Upload(id='upload-data', children='Upload a CSV', style=UPLOAD_STYLE),
    ], color='black', overlay_style=OVERLAY_STYLE_1),

    dcc.Store(id='stored-data'),

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
    Output('stored-data', 'data'),
    Output('upload-data', 'children'),
    Output('column-dropdown', 'options'),
    Output('column-dropdown', 'value'),
    Output('sequence-dropdown', 'options'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
    prevent_initial_call=True
)
@cache.memoize(timeout=3600)
def upload_data(contents, filename):
    if contents is None:
        return {}, 'Upload A CSV', [], None, []
    _, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    if filename.endswith('.csv'):
        data = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        
        # check for required columns
        required_columns = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']
        for column in required_columns:
            if not column in data.columns:
                return {}, html.Label(f'{filename} does not have column: {column}', style=ERROR_STYLE), [], None, []
            
        # check for FC columns
        fc_columns = [column for column in data.columns if 'FC' in column]
        if len(fc_columns) == 0:
            return {}, html.Label(f'{filename} does not have FC columns', style=ERROR_STYLE), [], None, []
            
        # add legend with parents
        gid_counts = data.GroupID.value_counts()
        gid_list = gid_counts[gid_counts > 1].index.tolist()
        parent_data = data[data.GroupID.apply(lambda x: x in gid_list)]
        parent_idx = parent_data[parent_data['Position'] == '0Z'].index.tolist()
        data['Legend'] = data['seq_origin'].copy()
        data.loc[parent_idx, 'Legend'] = 'parent'

        # format the data
        data = data[required_columns + fc_columns + ['Legend']]
        data = data.sort_values(['seq_origin', 'GroupID', 'Position']).reset_index(drop=True)

        # change datatypes to categorical
        data['GroupID'] = data['GroupID'].astype('category')
        data['Position'] = data['Position'].astype('category')
        data['seq_origin'] = data['seq_origin'].astype('category')
        data['sequence'] = data['sequence'].astype('category')
        data['Legend'] = data['Legend'].astype('category')
        data['Legend'] = data['Legend'].cat.add_categories(['selection'])
        for column in fc_columns + ['Input_CPM']:
            data[column] = pd.to_numeric(data[column], downcast='float')

        # serialize the DataFrame
        serialized_data = base64.b64encode(pickle.dumps(data)).decode('utf-8')

        return serialized_data, f'📄 {filename}', fc_columns, fc_columns[0], sorted(data.sequence.unique())
    
    return {}, html.Label(f'Error reading {filename}', style=ERROR_STYLE), [], None, []

@callback(
    Output('manhattan-plot', 'figure'),
    Output('sequence-dropdown', 'value'),
    Output('manhattan-plot', 'clickData'),
    Output('selection-data', 'data'),
    Input('stored-data', 'data'),
    Input('column-dropdown', 'value'),
    Input('scale-dropdown', 'value'),
    Input('sequence-dropdown', 'value'),
    Input('manhattan-plot', 'clickData'),
    Input('page-dropdown', 'value'),
    prevent_initial_call=True
)
# @cache.memoize(timeout=3600)
def update_graph(serialized_data, y_columns, scale, selected, click_data, pages):
    if not serialized_data or not y_columns:
        return {}, None, None, []
    if type(y_columns) == str:
        y_columns = [y_columns]
    
    data = pickle.loads(base64.b64decode(serialized_data))

    if click_data is None:
        pass
    else:
        selection = click_data['points'][0]['customdata'][4]
        if selected is None:
            selected = [selection]
        elif selection in selected:
            selected = [x for x in selected if x != selection]
        else:
            selected += [selection]

    # bring parents to the front
    parent_data = data[data['Legend'] == 'parent']
    not_parent_data = data[data['Legend'] != 'parent']
    data = pd.concat([not_parent_data, parent_data])

    # select sequences
    if selected is not None:
        selected_idx = data[data['sequence'].isin(selected)].index
        data.loc[selected_idx, 'Legend'] = 'selection'

        # selection data for export
        selection_data = data[data['sequence'].isin(selected)].copy()
        selection_columns = [x for x in selection_data.columns if '(log10)' not in x and '(sqrt)' not in x]
        selection_data = selection_data[selection_columns]
        selection_data = selection_data.drop('Legend', axis=1).to_dict('records')

        # bring selected to the front
        select_data = data[data['Legend'] == 'selection']
        not_select_data = data[data['Legend'] != 'selection']
        data = pd.concat([not_select_data, select_data])

    else:
        selection_data = []

    target_data_list = []
    for column in y_columns:
        target_data = data[['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM', 'Legend']]

        # select scale
        if scale == 'Square Root':
            plot_column = 'FC (sqrt)'
            target_data['Target'] = column
            target_data[plot_column] = data[column].apply(np.sqrt)

        elif scale == 'Log10':
            plot_column = 'FC (log10)'
            target_data['Target'] = column
            target_data[plot_column] = data[column].apply(np.log10)
        else:
            plot_column = 'FC'
            target_data['Target'] = column
            target_data[plot_column] = data[column]

        target_data_list.append(target_data)

    height = 100
    n_plots = len(y_columns)
    height += math.ceil(n_plots / pages) * 300
    
    data = pd.concat(target_data_list)
    hover_data = {'Legend': False, 'seq_origin': True, 'GroupID': True, 'Position': True, 'sequence': True, 'Input_CPM': True}
    fig = px.scatter(data, y=plot_column, color='Legend', facet_col='Target', facet_col_wrap=pages, hover_name='Legend', hover_data=hover_data, height=height, render_mode='pointcloud')

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