import numpy as np
import pandas as pd

import io
import base64
import plotly.express as px
from dash import Dash, dcc, dash_table, html, Input, Output, State, callback

app = Dash(__name__)

server = app.server

FONT_STYLE = {'fontFamily': 'monospace'}
UPLOAD_STYLE = {
    'height': '60px',
    'lineHeight': '60px',
    'borderWidth': '2px',
    'borderStyle': 'dashed',
    'borderRadius': '8px',
    'borderColor': 'lightgrey',
    'textAlign': 'center',
    'marginBottom': '0.6rem',
    **FONT_STYLE
}
LABEL_STYLE = {
    'fontWeight': 'bold',
    **FONT_STYLE
}
DROPDOWN_STYLE = {
    'marginBottom': '0.6rem',
    **FONT_STYLE
}

app.layout = [

    dcc.Upload(id='upload-data', children='Upload a CSV', style=UPLOAD_STYLE),
    html.Div(id='filename-display', style=DROPDOWN_STYLE),

    html.Label('Select column to plot', style=LABEL_STYLE),
    dcc.Dropdown(id='column-dropdown', style=DROPDOWN_STYLE),

    html.Label('Y-axis scale', style=LABEL_STYLE),
    dcc.Dropdown(id='scale-dropdown', options=['Linear', 'Square Root', 'Log10'], value='Log10', style=DROPDOWN_STYLE),

    html.Label('Select sequences', style=LABEL_STYLE),
    dcc.Dropdown(id='sequence-dropdown', style=DROPDOWN_STYLE, multi=True),
    
    dcc.Graph(id='manhattan-plot'),
    # dash_table.DataTable(id='data-table')
]

def parse_contents(contents, filename):
    try:
        _, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        return pd.read_csv(io.StringIO(decoded.decode('utf-8')))
    except:
        return None

@callback(
    [Output('column-dropdown', 'options'),
     Output('column-dropdown', 'value'),
     Output('sequence-dropdown', 'options'),
     Output('filename-display', 'children')],
    [Input('upload-data', 'contents')],
    [State('upload-data', 'filename')]
)
def update_dropdown(contents, filename):
    if contents is None:
        return [], None, [], ''
    data = parse_contents(contents, filename)
    if data is not None:
        required_cols = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']
        for col in required_cols:
            if not col in data.columns:
                return [], None, [], html.Label(f'{filename} does not have column: {col}', style={'color': 'red'})
        columns = [col for col in data.columns if 'FC' in col]
        sequences = sorted(data.sequence.unique())
        return columns, columns[0], sequences, f'📄 {filename}'
    return [], None, [], html.Label(f'Error loading {filename}', style={'color': 'red'})

@callback(
    Output('sequence-dropdown', 'value'),
    [Input('manhattan-plot', 'clickData')],
    [State('sequence-dropdown', 'value')]
)
def update_sequence_selection(click_data, selected_sequences):
    if click_data is None:
        return selected_sequences  # no update
    new_sequence = click_data['points'][0]['customdata'][4]
    if selected_sequences is None:
        return [new_sequence]
    elif new_sequence in selected_sequences:
        return selected_sequences  # avoid duplicates
    else:
        return selected_sequences + [new_sequence]

@callback(
    Output('manhattan-plot', 'figure'), #### START HERE , Output('data-table', 'data')
    [Input('upload-data', 'contents'),
     Input('column-dropdown', 'value'),
     Input('scale-dropdown', 'value'),
     Input('sequence-dropdown', 'value')],
     [State('upload-data', 'filename')]
)
def update_graph(contents, y_column, scale, selected_sequences, filename):
    if contents is None or y_column is None or scale is None:
        return {}
    
    data = parse_contents(contents, filename)
    if data is not None:

        required_cols = ['GroupID', 'Position', 'seq_origin', 'sequence', 'Input_CPM']
        ####

        # find parent sequences and label them
        data = data.sort_values(['seq_origin', 'GroupID', 'Position']).reset_index(drop=True)
        gid_counts = data.GroupID.value_counts()
        gid_list = gid_counts[gid_counts > 1].index.tolist()
        parent_data = data[data.GroupID.apply(lambda x: x in gid_list)]
        parent_idx = parent_data[parent_data['Position'] == '0Z'].index.tolist()
        data['Legend'] = data['seq_origin'].copy()
        data.loc[parent_idx, 'Legend'] = 'parent'
        parent_data = data[data['Legend'] == 'parent']
        not_parent_data = data[data['Legend'] != 'parent']
        data = pd.concat([not_parent_data, parent_data])

        if scale == 'Square Root':
            plot_column = f'{y_column} (sqrt)'
            data[plot_column] = data[y_column].apply(np.sqrt)
        elif scale == 'Log10':
            plot_column = f'{y_column} (log10)'
            data[plot_column] = data[y_column].apply(np.log10)
        else:
            plot_column = y_column

        hover_data = {'Legend': False, 'seq_origin': True, 'GroupID': True, 'Position': True, 'sequence': True, 'Input_CPM': True}
        fig = px.scatter(data, y=plot_column, color='Legend', title=y_column, hover_name='Legend', hover_data=hover_data, height=500)
        for trace in fig.data:
            if trace.name == 'parent':
                trace.marker.color = 'black'
            trace.marker.size = 5
        return fig
    
    return {}

if __name__ == '__main__':
    app.run(debug=True)