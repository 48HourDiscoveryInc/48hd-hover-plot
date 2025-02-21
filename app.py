import dash
from dash import Dash, html, dcc

app = Dash(__name__, use_pages=True)
server = app.server

FONT_STYLE = {'fontFamily': 'monospace'}

app.layout = html.Div([
    html.H3('48Hour Discovery Inc.', style=FONT_STYLE),
    html.Div([
        html.Div(
            dcc.Link(f"{page['name']} - {page['path']}", href=page['relative_path'])
        ) for page in dash.page_registry.values()
    ], style=FONT_STYLE),
    dash.page_container
])

if __name__ == '__main__':
    app.run(debug=True)