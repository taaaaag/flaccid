import plotly.graph_objects as go
import numpy as np

# Parse the data
data = {
    "components": [
        {"name": "FLAC Files", "type": "input", "color": "#FF6B6B"}, 
        {"name": "CLI Interface", "type": "input", "color": "#4ECDC4"}, 
        {"name": "Flaccid Plugin", "type": "input", "color": "#45B7D1"}, 
        {"name": "Main Tagger Engine", "type": "core", "color": "#96CEB4"}, 
        {"name": "Configuration Manager", "type": "core", "color": "#FFEAA7"}, 
        {"name": "Plugin Registry", "type": "core", "color": "#DDA0DD"}, 
        {"name": "Qobuz API", "type": "api", "color": "#74B9FF"}, 
        {"name": "Apple Music API", "type": "api", "color": "#FD79A8"}, 
        {"name": "MusicBrainz API", "type": "api", "color": "#FDCB6E"}, 
        {"name": "Discogs API", "type": "api", "color": "#6C5CE7"}, 
        {"name": "AcousticID API", "type": "api", "color": "#A29BFE"}, 
        {"name": "Tidal Tools", "type": "api", "color": "#FF7675"}, 
        {"name": "Metadata Aggregator", "type": "processing", "color": "#00B894"}, 
        {"name": "Conflict Resolver", "type": "processing", "color": "#00CEC9"}, 
        {"name": "Priority Matrix", "type": "processing", "color": "#FD79A8"}, 
        {"name": "Confidence Scorer", "type": "processing", "color": "#FDCB6E"}, 
        {"name": "Rich Terminal UI", "type": "output", "color": "#E17055"}, 
        {"name": "Tagged FLAC Files", "type": "output", "color": "#00B894"}, 
        {"name": "Backup System", "type": "output", "color": "#FD79A8"}
    ], 
    "flows": [
        {"from": "FLAC Files", "to": "Main Tagger Engine"}, 
        {"from": "CLI Interface", "to": "Main Tagger Engine"}, 
        {"from": "Flaccid Plugin", "to": "Main Tagger Engine"}, 
        {"from": "Main Tagger Engine", "to": "Configuration Manager"}, 
        {"from": "Main Tagger Engine", "to": "Plugin Registry"}, 
        {"from": "Main Tagger Engine", "to": "Qobuz API"}, 
        {"from": "Main Tagger Engine", "to": "Apple Music API"}, 
        {"from": "Main Tagger Engine", "to": "MusicBrainz API"}, 
        {"from": "Main Tagger Engine", "to": "Discogs API"}, 
        {"from": "Main Tagger Engine", "to": "AcousticID API"}, 
        {"from": "Main Tagger Engine", "to": "Tidal Tools"}, 
        {"from": "Qobuz API", "to": "Metadata Aggregator"}, 
        {"from": "Apple Music API", "to": "Metadata Aggregator"}, 
        {"from": "MusicBrainz API", "to": "Metadata Aggregator"}, 
        {"from": "Discogs API", "to": "Metadata Aggregator"}, 
        {"from": "AcousticID API", "to": "Metadata Aggregator"}, 
        {"from": "Tidal Tools", "to": "Metadata Aggregator"}, 
        {"from": "Metadata Aggregator", "to": "Conflict Resolver"}, 
        {"from": "Conflict Resolver", "to": "Priority Matrix"}, 
        {"from": "Priority Matrix", "to": "Confidence Scorer"}, 
        {"from": "Confidence Scorer", "to": "Rich Terminal UI"}, 
        {"from": "Rich Terminal UI", "to": "Tagged FLAC Files"}, 
        {"from": "Tagged FLAC Files", "to": "Backup System"}
    ]
}

# Brand colors mapping - using specified brand colors
type_colors = {
    'input': '#1FB8CD',     # Strong cyan
    'core': '#FFC185',      # Light orange
    'api': '#ECEBD5',       # Light green
    'processing': '#5D878F', # Cyan
    'output': '#D2BA4C'     # Moderate yellow
}

# Truncate names to 15 characters with better abbreviations
def truncate_name(name):
    if len(name) <= 15:
        return name
    # Smart truncation for common terms
    replacements = {
        'Interface': 'UI',
        'Configuration': 'Config',
        'Manager': 'Mgr',
        'Registry': 'Reg',
        'Aggregator': 'Agg',
        'Resolver': 'Res',
        'Confidence': 'Conf',
        'Scorer': 'Score',
        'Terminal': 'Term',
        'System': 'Sys',
        'Engine': 'Eng',
        'Plugin': 'Plug'
    }
    
    short_name = name
    for old, new in replacements.items():
        short_name = short_name.replace(old, new)
    
    if len(short_name) <= 15:
        return short_name
    return short_name[:15]

# Create more compact node positions
input_nodes = [c for c in data['components'] if c['type'] == 'input']
core_nodes = [c for c in data['components'] if c['type'] == 'core']
api_nodes = [c for c in data['components'] if c['type'] == 'api']
processing_nodes = [c for c in data['components'] if c['type'] == 'processing']
output_nodes = [c for c in data['components'] if c['type'] == 'output']

# Position nodes in layers with tighter spacing
node_positions = {}
layer_y = {'input': 5, 'core': 4, 'api': 3, 'processing': 2, 'output': 1}

# Position input nodes more compactly
for i, node in enumerate(input_nodes):
    node_positions[node['name']] = (i * 1.8, layer_y['input'])

# Position core nodes with Main Tagger Engine centered
main_tagger_x = 2.5
for i, node in enumerate(core_nodes):
    if node['name'] == 'Main Tagger Engine':
        node_positions[node['name']] = (main_tagger_x, layer_y['core'])
    else:
        offset = (i - 0.5) * 1.5
        node_positions[node['name']] = (main_tagger_x + offset, layer_y['core'])

# Position API nodes more compactly
for i, node in enumerate(api_nodes):
    node_positions[node['name']] = (i * 1.2, layer_y['api'])

# Position processing nodes
for i, node in enumerate(processing_nodes):
    node_positions[node['name']] = (i * 1.8 + 0.5, layer_y['processing'])

# Position output nodes
for i, node in enumerate(output_nodes):
    node_positions[node['name']] = (i * 1.8 + 1, layer_y['output'])

# Create edge traces with thicker arrows
edge_x = []
edge_y = []

for flow in data['flows']:
    from_pos = node_positions[flow['from']]
    to_pos = node_positions[flow['to']]
    edge_x.extend([from_pos[0], to_pos[0], None])
    edge_y.extend([from_pos[1], to_pos[1], None])

# Create the figure
fig = go.Figure()

# Add edges with thicker lines
fig.add_trace(go.Scatter(
    x=edge_x, y=edge_y,
    mode='lines',
    line=dict(width=3, color='#666666'),
    hoverinfo='none',
    showlegend=False
))

# Add nodes by type with consistent circle markers
for comp_type, color in type_colors.items():
    nodes_of_type = [c for c in data['components'] if c['type'] == comp_type]
    if not nodes_of_type:
        continue
        
    node_x = [node_positions[node['name']][0] for node in nodes_of_type]
    node_y = [node_positions[node['name']][1] for node in nodes_of_type]
    node_text = [truncate_name(node['name']) for node in nodes_of_type]
    
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y,
        mode='markers+text',
        marker=dict(
            size=40, 
            color=color, 
            line=dict(width=3, color='white')
        ),
        text=node_text,
        textposition="middle center",
        textfont=dict(size=11, color='black', family='Arial Black'),
        name=comp_type.title(),
        hoverinfo='text',
        hovertext=[f"{comp_type.title()}: {name}" for name in node_text]
    ))

# Update layout with no annotations
fig.update_layout(
    title='FLAC Metadata Tagger Architecture',
    showlegend=True,
    legend=dict(orientation='h', yanchor='bottom', y=1.05, xanchor='center', x=0.5),
    xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
    yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
    plot_bgcolor='white'
)

# Save the chart
fig.write_image("flac_tagger_architecture.png")