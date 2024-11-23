import numpy as np
import pandas as pd

import io
import base64
import plotly.express as px

from dash import Dash
from dash import dash_table
from dash import dcc, html, callback
from dash import Input, Output, State

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
ERROR_STYLE = {
    'color': 'red',
    **FONT_STYLE
}

app.layout = html.Div([
    dcc.Upload(id='upload-data', style=UPLOAD_STYLE),
    dcc.Store(id='stored-data'),

    html.Div([
        html.Div([
            html.Label('Select column', style=LABEL_STYLE),
            dcc.Dropdown(id='column-dropdown', value='', style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '250px'}),

        html.Div([
            html.Label('Y-axis scale', style=LABEL_STYLE),
            dcc.Dropdown(id='scale-dropdown', options=['Linear', 'Square Root', 'Log10'], value='Log10', style=DROPDOWN_STYLE),
        ], style={'margin': '10px', 'width': '150px'}),

        html.Div([
            html.Label('Select sequences', style=LABEL_STYLE),
            dcc.Dropdown(id='sequence-dropdown', style=DROPDOWN_STYLE, multi=True),
        ], style={'flex': '1', 'margin': '10px'}),
    ], style={'display': 'flex', 'flexDirection': 'row', 'gap': '10px'}),

    dcc.Graph(id='manhattan-plot'),
    dash_table.DataTable(id='selection-data', page_action='none', export_format='xlsx', style_table=TABLE_STYLE)
])

@callback(
    Output('stored-data', 'data'),
    Output('upload-data', 'children'),
    Input('upload-data', 'contents'),
    State('upload-data', 'filename'),
)
def upload_data(contents, filename):
    if contents is None:
        return {}, 'Upload A CSV'
    _, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    if filename.endswith('.csv'):
        data = pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        
        # check for required columns
        required_columns = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']
        for column in required_columns:
            if not column in data.columns:
                return {}, html.Label(f'{filename} does not have column: {column}', style=ERROR_STYLE)
            
        # check for FC columns
        fc_columns = [column for column in data.columns if 'FC' in column]
        if len(fc_columns) == 0:
            return {}, html.Label(f'{filename} does not have FC columns', style=ERROR_STYLE)
            
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
        # columns = [{'name': i, 'id': i} for i in data.columns]
        return data.to_dict('records'), f'📄 {filename}'
    return {}, html.Label(f'Error reading {filename}', style=ERROR_STYLE)

@callback(
    Output('column-dropdown', 'options'),
    Output('column-dropdown', 'value'),
    Output('sequence-dropdown', 'options'),
    Input('stored-data', 'data')
)
def update_dropdown(data):
    data = pd.DataFrame(data)
    if not data.empty:
        fc_columns = [column for column in data.columns if 'FC' in column]
        sequences = sorted(data.sequence.unique())
        return fc_columns, fc_columns[0], sequences
    return [], None, []

@callback(
    Output('sequence-dropdown', 'value'),
    Input('manhattan-plot', 'clickData'),
    State('sequence-dropdown', 'value')
)
def update_selection(click_data, selected):
    if click_data is None:
        return selected
    selection = click_data['points'][0]['customdata'][4]
    if selected is None:
        return [selection]
    elif selection in selected:
        selected = [x for x in selected if x != selection]
        return selected
    else:
        return selected + [selection]
    
@callback(
    Output('selection-data', 'data'),
    Input('stored-data', 'data'),
    Input('sequence-dropdown', 'value')
)
def update_table(data, selected):
    data = pd.DataFrame(data)
    if not data.empty and selected is not None:
        selection_data = data[data['sequence'].isin(selected)]
        return selection_data.drop('Legend', axis=1).to_dict('records')
    return []

@callback(
    Output('manhattan-plot', 'figure'),
    Input('stored-data', 'data'),
    Input('column-dropdown', 'value'),
    Input('scale-dropdown', 'value'),
    Input('sequence-dropdown', 'value')
)
def update_graph(data, y_column, scale, selected):
    data = pd.DataFrame(data)
    if not data.empty:

        if scale == 'Square Root':
            plot_column = f'{y_column} (sqrt)'
            data[plot_column] = data[y_column].apply(np.sqrt)
        elif scale == 'Log10':
            plot_column = f'{y_column} (log10)'
            data[plot_column] = data[y_column].apply(np.log10)
        else:
            plot_column = y_column

        # bring parents to the front
        parent_data = data[data['Legend'] == 'parent']
        not_parent_data = data[data['Legend'] != 'parent']
        data = pd.concat([not_parent_data, parent_data])

        if selected is not None:
            selected_idx = data[data['sequence'].isin(selected)].index
            data.loc[selected_idx, 'Legend'] = 'selection'

        # bring selected to the front
        select_data = data[data['Legend'] == 'selection']
        not_select_data = data[data['Legend'] != 'selection']
        data = pd.concat([not_select_data, select_data])

        hover_data = {'Legend': False, 'seq_origin': True, 'GroupID': True, 'Position': True, 'sequence': True, 'Input_CPM': True}
        fig = px.scatter(data, y=plot_column, color='Legend', hover_name='Legend', hover_data=hover_data, height=500)

        for trace in fig.data:
            if trace.name == 'parent':
                trace.marker.color = 'black'
                trace.marker.size = 5
            elif trace.name == 'selection':
                trace.marker.color = 'red'
                trace.marker.line = {'color': 'black', 'width': 2}
                trace.marker.size = 8
            else:
                trace.marker.size = 5
        return fig
    return {}

if __name__ == '__main__':
    app.run(debug=True)