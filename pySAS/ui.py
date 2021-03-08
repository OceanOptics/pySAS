import dash
import dash_core_components as dcc
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash.dependencies import Input, Output, State
from flask import request
import plotly.graph_objs as go
import logging
from time import time, gmtime, strftime
from math import isnan
import os
import base64
from zipfile import BadZipFile
from pySAS import __version__, CFG_FILENAME, ui_log_queue
from pySAS.runner import Runner, get_true_north_heading

STATUS_REFRESH_INTERVAL = 1000
HYPERSAS_READING_INTERVAL = 2000

runner = Runner(CFG_FILENAME)

logger = logging.getLogger('ui')

app = dash.Dash(__name__)
app.title = 'pySAS v' + __version__


##########
# Layout #
##########
figure_sun_model = html.P("")
figure_spectrum_history = html.P("")

if runner.es:
    core_instruments_names = "HyperSAS+Es"
else:
    core_instruments_names = "HyperSAS"

# Graph options
graph_config = {'displaylogo': False, 'editable': False, 'displayModeBar': False, 'showTips': False}

controls_layout = [
    dcc.Location(id='location', refresh=True),
    # Header
    html.P(['pySAS v' + __version__], style={'fontSize': '1.8vw', 'marginBottom': '0.3em'}, className='text-left'),
    html.H4([html.Span("17:34:04", id='time'), " UTC"],
            style={'fontFamily': 'Menlo', 'fontSize': '1.8vw', 'marginBottom': '0em'}, className='text-center'),
    html.P('Nov 26, 2019', id='date', style={'fontFamily': 'Menlo', 'fontSize': '1.8vw'}, className='text-center'),

    # Status + Controls
    dbc.FormGroup([dbc.Label("Mode", html_for="operation_mode", width=4),
                   dbc.Col(dbc.Select(id="operation_mode", bs_size='sm',
                                      options=[{'label': "Manual", 'value': 'manual'},
                                               {'label': "Auto", 'value': 'auto'}]),
                           width=8),
                   ], row=True),
    dbc.FormGroup([dbc.Label(core_instruments_names, html_for="hypersas_activate", width=4, className='text-nowrap'),
                   dbc.Col([dbc.Checklist(id="hypersas_switch", switch=True, inline=False,
                                          options=[{'label': "", 'value': 'on'}],
                                          style={'marginRight': '-0.5em'},
                                          className='mt-1 ml-1'),
                            dbc.Badge("Logging", id='hypersas_status', pill=True, color="success",
                                      className="mt-2 ml-1 d-none")
                            ], width=8, className='text-right'),
                   ], row=True),
    # Switch toggle to status badge when in automatic mode
    dbc.FormGroup([dbc.Label("GPS", html_for="gps_status", width=3, className='text-nowrap'),
                   dbc.Col([dbc.Badge("???", id='gps_flag_fix', pill=True, color="light", className="mt-2 ml-1"),
                            dbc.Badge("???", id='gps_flag_hdg', pill=True, color="light", className="mt-2 ml-1"),
                            dbc.Badge("No Time", id='gps_flag_time', pill=True, color="danger", className="mt-2 ml-1"),
                            dbc.Checklist(id="gps_switch", switch=True, inline=False,
                                          options=[{'label': "", 'value': 'on'}],
                                          style={'marginRight': '-0.5em', 'display': 'inline-block'},
                                          className='mt-1 ml-1'),
                            ], width=9, className='text-right'),
                   ], row=True),
    dbc.FormGroup(
        [dbc.Label("Tower 69°", id='tower_label', html_for="indexing_table_status", width=3, className='text-nowrap'),
         dbc.Col([dbc.Badge("Stall", id='tower_stall_flag', pill=True, href="#", color="danger", className="mt-2 ml-1"),
                  dbc.Badge("Zero", id='tower_zero', pill=True, href="#", color="secondary", className="mt-2 ml-1"),
                  dbc.Checklist(id="tower_switch", switch=True, inline=False,
                                options=[{'label': "", 'value': 'on'}],
                                style={'marginRight': '-0.5em', 'display': 'inline-block'},
                                className="mt-1 ml-1")
                  ], width=9, className='text-right'),
         ], row=True),
    dcc.Slider(id='tower_orientation', min=-180, max=180, step=1, value=96, included=False, disabled=False,
               marks={i: '{}°'.format(i) for i in [-160, -80, 0, 80, 160]},
               tooltip={'always_visible': False, 'placement': 'bottom'},
               className='d-none'),  # Hide bar when switch menu

    # Settings
    html.Div([
        html.H6('Settings',
                className='sidebar-heading d-flex justify-content-between align-items-center mt-4 mb-2 text-muted'),
        # Tower Valid Orientation Range
        dbc.FormGroup([
            dbc.Label("Tower Valid Range"),
            dbc.InputGroup([
                dbc.InputGroupAddon("Port side", addon_type="prepend"),
                dbc.Input(id='tower_valid_orientation_prt', type='number', min=-180, max=360, step=1, debounce=True),
                dbc.InputGroupAddon("°", addon_type="append")
            ], className="mb-3", size='sm'),
            dbc.InputGroup([
                dbc.InputGroupAddon("Starboard", addon_type="prepend"),
                dbc.Input(id='tower_valid_orientation_stb', type='number', min=-180, max=360, step=1, debounce=True),
                dbc.InputGroupAddon("°", addon_type="append")
            ], className="mb-3", size='sm'),
        ]),
        # GPS Orientation
        dbc.FormGroup([
            dbc.Label("GPS Orientation"),
            dbc.InputGroup([
                dbc.Input(id='gps_orientation', type='number', min=-180, max=360, step=1, debounce=True),
                dbc.InputGroupAddon("°", addon_type="append")
            ], className="mb-3", size='sm'),
        ]),
        # Sun Elevation
        dbc.FormGroup([
            dbc.Label("Sun Elevation"),
            dbc.InputGroup([
                dbc.InputGroupAddon("Min", addon_type="prepend"),
                dbc.Input(id='min_sun_elevation', type='number', min=0, max=90, step=1, debounce=True),
                dbc.InputGroupAddon("°", addon_type="append")
            ], className="mb-3", size='sm'),
            dbc.InputGroup([
                dbc.InputGroupAddon("Refresh", addon_type="prepend"),
                dbc.Input(id='refresh_sun_elevation', type='number', min=0, max=90, step=1, debounce=True),
                dbc.InputGroupAddon("s", addon_type="append")
            ], className="mb-3", size='sm')
        ]),
        # Filtering Algorithm
        # dbc.FormGroup([dbc.Label("Filtering", html_for="filtering"),
        #                dbc.Select(id="filtering", bs_size='sm',
        #                           options=[{'label': "None", 'value': 'none'}, {'label': "Kalman", 'value': 'kalman'}]),
        #                ]),
        # HyperSAS Device File
        dbc.FormGroup([dbc.Label(core_instruments_names + " Device File", html_for="trigger_device_file_modal"),
                       dbc.Button("Select or Upload", id="trigger_device_file_modal", outline=True, color='dark', size='sm')]),
        dbc.Button("Halt", id="trigger_halt_modal", outline=True, color="secondary", size='sm', block=True,
                   className="mt-4 mb-2")
    ], className='sidebar-settings w-100'),

    # Modals
    dbc.Modal([dbc.ModalHeader(core_instruments_names + " Device File"),
               dbc.ModalBody(dbc.Row([
                   dbc.Col([
                   dbc.Alert("Success! Device file imported.", id='device_file_modal_alert_success', color='success',
                             is_open=False, duration=4000),
                   dbc.Alert("Unable to import device file.", id='device_file_modal_alert_fail', color='danger',
                             is_open=False, duration=10000),
                   dbc.Alert("Unable to load device file.", id='device_file_modal_alert_fail_sel', color='danger',
                             is_open=False, duration=10000)], md=12),
                   dbc.Col(html.Div([
                           dbc.FormGroup([dbc.Label('Select device file:', html_for='select_device_file'),
                           dbc.RadioItems(id='select_device_file', options=[], labelCheckedStyle={"color": "green"})])]), md=6),
                   dbc.Col(dcc.Upload(id='upload_device_file', children=html.Div(['Drag and Drop or ',
                                                                        html.A('Select Device Files',
                                                                               style={'color': '#007bff',
                                                                                      'cursor': 'pointer'})]),
                                      style={'padding': '40px 40px', 'borderWidth': '1px', 'borderStyle': 'dashed',
                                             'borderRadius': '5px', 'textAlign': 'center', 'margin': '5px'}), md=6)])),
               dbc.ModalFooter([dbc.Button("Close", id="device_file_modal_close", className="mr-1")]),
               ],
              id="device_file_modal", is_open=False, backdrop='static', keyboard=False, centered=True),
    dbc.Modal([dbc.ModalBody("Are you sure you want to shut down pySAS now ?", id='halt_modal_body'),
               dbc.ModalFooter([dbc.Button("Cancel", id="halt_modal_close", className="mr-1"),
                                dbc.Button("Shut Down", id="halt_modal_halt", outline=True)]),
               ],
              id="halt_modal", is_open=False, backdrop='static', keyboard=False, centered=True),
    dbc.Modal([dbc.ModalHeader("Error"),
               dbc.ModalBody("Unknown error", id='error_modal_body'),
               dbc.ModalFooter([dbc.Button("Ignore", id="error_modal_close", className="mr-1"),
                                dbc.Button("Reboot", id="error_modal_reboot", outline=True)])],
              id="error_modal", is_open=False, backdrop='static', keyboard=False, centered=True)
]

app.layout = dbc.Container([dbc.Row([
    html.Main([
        dbc.Row([
            dbc.Col(dcc.Graph(id='figure_system_orientation', style={'height': '100%'}, config=graph_config), md=4),
            # dbc.Col(figure_system_orientation, md=4),
            dbc.Col(dcc.Graph(id='figure_spectrums', style={'height': '100%'}, config=graph_config), md=8)
            # dbc.Col(figure_last_spectrum, md=8)
        ], className='h-50'),
        dbc.Row([
            dbc.Col(figure_sun_model, md=4),
            dbc.Col(figure_spectrum_history, md=8)
        ], className='h-50')
    ], className='col-md-9 col-lg-10 mr-sm-auto px-4'),
    html.Nav([
        html.Div(controls_layout, className='sidebar-sticky')
    ], className='col-md-3 col-lg-2 d-none d-md-block bg-light sidebar'),
    html.Div(id='no_output_0', className='d-none'),
    html.Div(id='no_output_1', className='d-none'),
    html.Div(id='no_output_2', className='d-none'),
    html.Div(id='operation_mode_last_value', className='d-none'),  # , children=runner.operation_mode),
    html.Div(id='tower_switch_last_value', className='d-none'),
    # , children=['on'] if runner.indexing_table.alive else []),
    html.Div(id='tower_zero_last_n_clicks', className='d-none', children='init'),
    html.Div(id='get_switch_n_updates', className='d-none'),
    html.Div(id='get_switch_last_n_updates', className='d-none'),
    html.Div(id='get_switch_last_n_updates_2', className='d-none'),
    html.Div(id='get_gps_switch_last_n_updates', className='d-none'),
    dbc.Button(id='load_settings', className='d-none'),
    html.Div(id='tower_valid_orientation_init', className='d-none'),
    html.Div(id='gps_orientation_init', className='d-none'),
    html.Div(id='min_sun_elevation_init', className='d-none'),
    html.Div(id='refresh_sun_elevation_init', className='d-none'),
    html.Div(id='device_file_modal_update_options', className='d-None'),
    dcc.Interval(id='status_refresh_interval', interval=STATUS_REFRESH_INTERVAL),
    dcc.Interval(id='hypersas_reading_interval', interval=HYPERSAS_READING_INTERVAL)
], className='h-100')], fluid=True)


##########
# Init
@app.callback([Output('operation_mode', 'value'),
               Output('tower_valid_orientation_prt', 'value'), Output('tower_valid_orientation_stb', 'value'),
               Output('gps_orientation', 'value'),
               Output('min_sun_elevation', 'value'), Output('refresh_sun_elevation', 'value')],
              [Input('load_settings', 'n_clicks')])
def set_content_on_page_load(n_clicks):
    if n_clicks is None:
        logger.debug(f'set_content_on_page_load: {runner.operation_mode}, '
                     f'{runner.pilot.tower_limits[0]}, {runner.pilot.tower_limits[1]}, '
                     f'{runner.pilot.compass_zero}, {runner.min_sun_elevation}, {runner.refresh_delay}')
        return runner.operation_mode, runner.pilot.tower_limits[0], runner.pilot.tower_limits[1], \
            runner.pilot.compass_zero, runner.min_sun_elevation, runner.refresh_delay
    raise dash.exceptions.PreventUpdate()


##########
# Clock
@app.callback([Output('time', 'children'), Output('date', 'children')],
              [Input('status_refresh_interval', 'n_intervals')])
def update_time(_):
    dt = gmtime()
    return strftime("%-H:%M:%S", dt), strftime("%b %d, %Y", dt)


#################
# Operation Mode
@app.callback([Output('tower_switch', 'className'),
               Output('tower_orientation', 'className'), Output('tower_zero', 'className'),
               Output('gps_switch', 'className'),
               Output('hypersas_switch', 'className'), Output('hypersas_status', 'className'),
               Output('operation_mode_last_value', 'children'), Output('tower_switch_last_value', 'children'),
               Output('get_switch_last_n_updates', 'children')],
              [Input('operation_mode', 'value'), Input('tower_switch', 'value')],
              [State('operation_mode_last_value', 'children'), State('tower_switch_last_value', 'children'),
               State('get_switch_n_updates', 'children'), State('get_switch_last_n_updates', 'children')])
def set_operation_mode(operation_mode, tower_switch, operation_mode_previous, tower_switch_previous,
                       get_switch_n_updates, get_switch_last_n_updates):
    trigger = dash.callback_context.triggered[0]['prop_id']
    logger.debug(f'set_operation_mode: {operation_mode}, {tower_switch}, '
                 f'{operation_mode_previous}, {tower_switch_previous}, '
                 f'{get_switch_n_updates}, {get_switch_last_n_updates}, {trigger}')
    if operation_mode is None and tower_switch is None:
        logger.debug('set_operation_mode: loading')
        raise dash.exceptions.PreventUpdate()
    if trigger == 'operation_mode.value':
        if operation_mode not in ['auto', 'manual']:
            logger.warning('set_operation_mode: invalid operation mode ' + str(operation_mode))
            raise dash.exceptions.PreventUpdate()
        if operation_mode == operation_mode_previous:
            logger.debug('set_operation_mode: operation_mode already up to date')
            raise dash.exceptions.PreventUpdate()
        if operation_mode_previous is None:
            logger.debug('set_operation_mode: init operation_mode')
        else:
            runner.operation_mode = operation_mode
            runner.set_cfg_variable('Runner', 'operation_mode', operation_mode)
            if runner.operation_mode == 'auto':
                runner.start_auto()
            else:
                runner.stop_auto()
    elif trigger == 'tower_switch.value':
        if get_switch_n_updates != get_switch_last_n_updates:
            logger.debug('set_operation_mode: called by get_switch')
        elif tower_switch not in [["on"], []]:
            logger.warning('set_operation_mode: invalid tower switch ' + str(tower_switch))
            raise dash.exceptions.PreventUpdate()
        elif tower_switch == tower_switch_previous:
            logger.debug('set_operation_mode: tower_switch already up to date')
            raise dash.exceptions.PreventUpdate()
        elif runner.operation_mode != 'manual':
            logger.debug('set_operation_mode: tower_switch modification unauthorized')
            raise dash.exceptions.PreventUpdate()
        elif tower_switch_previous is None:
            logger.debug('set_operation_mode: init tower_switch')
        else:
            if tower_switch:
                if not runner.indexing_table.start():
                    logger.debug('unable to start indexing tower')
            else:
                runner.indexing_table.stop()
    # Get Operation Mode
    tower_switch_class_name = 'mt-1 ml-1'
    tower_orientation_class_name = '' #'wide-slider'
    tower_zero_class_name = 'mt-2 ml-1'
    gps_switch_class_name = 'mt-1 ml-1'
    hypersas_switch_class_name = 'mt-1 ml-1'
    hypersas_status_class_name = 'mt-2 ml-1'
    if runner.operation_mode == 'auto':
        tower_switch_class_name = 'd-none'
        tower_orientation_class_name = 'd-none'
        tower_zero_class_name = 'd-none'
        gps_switch_class_name = 'd-none'
        hypersas_switch_class_name = 'd-none'
    elif runner.operation_mode == 'manual':
        hypersas_status_class_name = 'd-none'
        # Get Indexing Table Status
        if not runner.indexing_table.alive:
            tower_orientation_class_name = 'd-none'
            tower_zero_class_name = 'd-none'
    else:
        logger.warning('set_operation_mode: unknown operation mode ' + str(runner.operation_mode))
    if runner.indexing_table.alive:
        tower_state = ['on']
    else:
        tower_state = []
    # Update UI
    return tower_switch_class_name, tower_orientation_class_name, tower_zero_class_name, gps_switch_class_name, \
           hypersas_switch_class_name, hypersas_status_class_name, runner.operation_mode, tower_state, get_switch_n_updates


@app.callback([Output('hypersas_switch', 'value'), Output('gps_switch', 'value'), Output('tower_switch', 'value'),
               Output('get_switch_n_updates', 'children')],
              [Input('status_refresh_interval', 'n_intervals')],
              [State('hypersas_switch', 'value'), State('gps_switch', 'value'), State('tower_switch', 'value'),
               State('get_switch_n_updates', 'children')])
def get_switch(n_intervals, current_hypersas_switch_value, current_gps_switch_value, current_tower_switch_value,
               n_updates):
    if n_intervals is None:
        logger.debug('get_switch: loading')
    if runner.hypersas.alive:
        hypersas_switch_value = ['on']
    else:
        hypersas_switch_value = []
    if runner.gps.alive:
        gps_switch_value = ['on']
    else:
        gps_switch_value = []
    if runner.indexing_table.alive:
        tower_switch_value = ['on']
    else:
        tower_switch_value = []
    if hypersas_switch_value == current_hypersas_switch_value and \
            gps_switch_value == current_gps_switch_value and \
            tower_switch_value == current_tower_switch_value:
        raise dash.exceptions.PreventUpdate()
    # Update counter to prevent chained callback of set_operation_mode
    n_updates = 1 if n_updates is None else n_updates + 1
    return hypersas_switch_value, gps_switch_value, tower_switch_value, n_updates


##########
# HyperSAS
@app.callback(Output('get_switch_last_n_updates_2', 'children'),
              [Input('hypersas_switch', 'value'), Input('hypersas_switch', 'className')],
              [State('get_switch_n_updates', 'children'), State('get_switch_last_n_updates_2', 'children')])
def set_hypersas_switch(value, _, get_switch_n_updates, get_switch_last_n_updates):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if value is None:
        logger.debug('set_hypersas_switch: loading')
        raise dash.exceptions.PreventUpdate()
    if get_switch_n_updates != get_switch_last_n_updates:
        logger.debug('set_hypersas_switch: called by get_switch')
        return get_switch_n_updates
    if trigger == 'hypersas_switch.value':
        if value == ['on']:
            logger.debug('set_hypersas_switch: start')
            runner.gps.start_logging()
            if runner.es:
                runner.es.start()
            runner.hypersas.start()
        else:
            logger.debug('set_hypersas_switch: stop')
            runner.hypersas.stop()
            runner.gps.stop_logging()
            if runner.es:
                runner.es.stop()
    elif trigger == 'hypersas_switch.className':
        logger.debug('set_hypersas_switch: called by set_operation_mode')
    raise dash.exceptions.PreventUpdate()


@app.callback([Output('hypersas_status', 'children'), Output('hypersas_status', 'color')],
              [Input('status_refresh_interval', 'n_intervals')],
              [State('hypersas_status', 'children')])
def get_hypersas_status(_, state):
    if runner.hypersas.alive:
        if state == 'Logging':
            raise dash.exceptions.PreventUpdate()
        return 'Logging', 'success'
    else:
        if state == 'Off':
            raise dash.exceptions.PreventUpdate()
        return 'Off', 'warning'


##########
# GPS
@app.callback(Output('get_gps_switch_last_n_updates', 'children'), [Input('gps_switch', 'value')],
              [State('get_switch_n_updates', 'children'), State('get_gps_switch_last_n_updates', 'children')])
def set_gps_switch(value, get_switch_n_updates, get_switch_last_n_updates):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if value is None:
        logger.debug('set_gps_switch: loading')
        raise dash.exceptions.PreventUpdate()
    if get_switch_n_updates != get_switch_last_n_updates:
        logger.debug('set_gps_switch: called by get_switch')
        return get_switch_n_updates
    if trigger == 'gps_switch.value':
        if value == ['on']:
            logger.debug('set_gps_switch: start')
            runner.gps.start()
        else:
            logger.debug('set_gps_switch: stop')
            runner.gps.stop()
    elif trigger == 'set_gps_switch.className':
        logger.debug('set_gps_switch: called by set_operation_mode')
    raise dash.exceptions.PreventUpdate()


@app.callback([Output('gps_flag_hdg', 'children'), Output('gps_flag_hdg', 'color'), Output('gps_flag_hdg', 'className'),
               Output('gps_flag_fix', 'children'), Output('gps_flag_fix', 'color'), Output('gps_flag_fix', 'className'),
               Output('gps_flag_time', 'className')],
              [Input('status_refresh_interval', 'n_intervals')])
def get_gps_flags(_):
    if runner.operation_mode == 'manual' and not runner.gps.alive:
        return dash.no_update, dash.no_update, 'd-none', \
               dash.no_update, dash.no_update, 'd-none', \
               'd-none'

    if runner.gps.fix_type < 2:
        hdg = 'No Hdg', 'warning', 'd-none'
    elif time() - runner.gps.packet_relposned_received > runner.DATA_EXPIRED_DELAY:
        hdg = 'No Hdg', 'warning', 'mt-2 ml-1'
    elif runner.gps.heading_valid:
        hdg = 'Hdg', 'success', 'mt-2 ml-1'
    else:
        hdg = 'No Hdg', 'danger', 'mt-2 ml-1'

    if time() - runner.gps.packet_pvt_received > runner.DATA_EXPIRED_DELAY:
        fix = 'Off', 'warning', 'mt-2 ml-1'
    elif runner.gps.fix_type == 0:
        fix = 'No Fix', 'danger', 'mt-2 ml-1'
    elif runner.gps.fix_type == 1:  # Dead reckoning
        fix = 'DR', 'warning', 'mt-2 ml-1'
    elif runner.gps.fix_type == 2:
        fix = '2D-Fix', 'info', 'mt-2 ml-1'
    elif runner.gps.fix_type == 3:
        fix = '3D-Fix', 'success', 'mt-2 ml-1'
    elif runner.gps.fix_type == 4:
        fix = 'GNSS+DR', 'info', 'mt-2 ml-1'
    elif runner.gps.fix_type == 5:
        fix = 'Time Only', 'warning', 'mt-2 ml-1'
    else:
        fix = 'Unknown', 'danger', 'mt-2 ml-1'

    if runner.gps.datetime_valid:
        dt = 'd-none',
    else:
        dt = 'mt-2 ml-1',

    return hdg + fix + dt


##########
# Tower
@app.callback(Output('tower_stall_flag', 'className'),
              [Input('tower_stall_flag', 'n_clicks'), Input('status_refresh_interval', 'n_intervals')],
              [State('tower_stall_flag', 'className')])
def set_tower_stall_flag(n_clicks, _, state):
    trigger = dash.callback_context.triggered[0]['prop_id'].split('.')[1]
    if trigger == 'n_intervals':
        # Automatic update with time interval
        if runner.indexing_table.stalled and runner.indexing_table.alive:
            if state == 'mt-2 ml-1 d-none' or state is None:
                logger.debug('set_tower_stall_flag: true')
                return 'mt-2 ml-1'
            else:
                raise dash.exceptions.PreventUpdate()
        else:
            if state == 'mt-2 ml-1' or state is None:
                logger.debug('set_tower_stall_flag: false')
                return 'mt-2 ml-1 d-none'
            else:
                raise dash.exceptions.PreventUpdate()
    elif trigger == 'n_clicks' and n_clicks:
        # User clicked reset button
        logger.debug('set_tower_stall_flag: reset')
        runner.indexing_table.reset_stall_flag()
        return 'mt-2 ml-1 d-none'
    else:  # trigger is empty and n_clicks is None
        # Special case of initialization
        logger.debug('set_tower_stall_flag: loading')
        if runner.indexing_table.stalled and runner.indexing_table.alive:
            return 'mt-2 ml-1'
        else:
            return 'mt-2 ml-1 d-none'


@app.callback(Output('tower_orientation', 'value'),
              [Input('tower_zero', 'n_clicks'), Input('operation_mode', 'value')])
def set_tower_zero(n_clicks, _):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if trigger == 'tower_zero.n_clicks' and n_clicks:
        logger.debug('set_tower_zero: zeroed')
        runner.indexing_table.reset_position_zero()
        return 0
    else:
        logger.debug('set_tower_zero: get tower orientation')
        return runner.indexing_table.position


@app.callback([Output('tower_label', 'children'), Output('tower_zero_last_n_clicks', 'children')],
              [Input('tower_orientation', 'value'), Input('tower_orientation', 'className'),
               Input('status_refresh_interval', 'n_intervals')],
              [State('tower_label', 'children'),
               State('tower_zero', 'n_clicks'), State('tower_zero_last_n_clicks', 'children')])
def set_tower_orientation(orientation, _, _2, label_state, zero_n_clicks, zero_n_clicks_last):
    trigger = dash.callback_context.triggered[0]['prop_id']

    if trigger == 'status_refresh_interval.n_intervals':
        if isnan(runner.indexing_table.position):
            tower_label = 'Tower ??°'
        else:
            tower_label = 'Tower %d°' % runner.indexing_table.position
        if tower_label == label_state:
            raise dash.exceptions.PreventUpdate()
        return tower_label, zero_n_clicks
    if trigger == 'tower_orientation.className':
        logger.debug('set_tower_orientation: called by set_operation_mode')
        raise dash.exceptions.PreventUpdate()
    if trigger == 'tower_orientation.value':
        if orientation is None:
            logger.debug('set_tower_orientation: loading')
            raise dash.exceptions.PreventUpdate()
        if zero_n_clicks != zero_n_clicks_last:
            if zero_n_clicks_last == 'init':
                logger.debug('set_tower_orientation: called by set_tower_zero while loading')
                return 'Tower ??°', zero_n_clicks
            else:
                logger.debug('set_tower_orientation: called by set_tower_zero')
            return 'Tower 0°', zero_n_clicks
        if runner.indexing_table.alive:
            logger.debug('set_tower_orientation: ' + str(orientation))
            runner.indexing_table.set_position(orientation)
            return 'Tower %d°' % orientation, zero_n_clicks
        logger.warning('set_tower_orientation: unable, tower not alive')
        raise dash.exceptions.PreventUpdate()
    logger.warning('set_tower_orientation: unknown trigger ' + trigger)
    raise dash.exceptions.PreventUpdate()


###########
# Settings
@app.callback(Output('tower_valid_orientation_init', 'children'),
              [Input('tower_valid_orientation_prt', 'value'), Input('tower_valid_orientation_stb', 'value')],
              [State('tower_valid_orientation_init', 'children')])
def set_tower_valid_orientation(prt_value, stb_value, init):
    if prt_value is None or stb_value is None:
        if init:
            logger.debug('set_tower_valid_orientation: None value ignored')
        else:
            logger.debug(f'set_tower_valid_orientation: loading')
        raise dash.exceptions.PreventUpdate()
    if not init:
        logger.debug(f'set_tower_valid_orientation: init')
        return True
    logger.debug(f'set_tower_valid_orientation({prt_value}, {stb_value})')
    runner.pilot.set_tower_limits([prt_value, stb_value])
    runner.set_cfg_variable('AutoPilot', 'valid_indexing_table_orientation_limits', [prt_value, stb_value])
    raise dash.exceptions.PreventUpdate()


@app.callback(Output('gps_orientation_init', 'children'),
              [Input('gps_orientation', 'value'), Input('gps_orientation', 'loading_state')],
              [State('gps_orientation_init', 'children')])
def set_gps_orientation(value, _, init):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if trigger == 'gps_orientation.value':
        if init is None:
            logger.debug('set_gps_orientation: init')
            return True
        if value is None:
            logger.debug('set_gps_orientation: None value ignored')
            raise dash.exceptions.PreventUpdate()
        logger.debug('set_gps_orientation: ' + str(value))
        runner.pilot.compass_zero = value
        runner.set_cfg_variable('AutoPilot', 'gps_orientation_on_ship', value)
    elif trigger == 'gps_orientation.loading_state':
        logger.debug('set_gps_orientation: loading')
    raise dash.exceptions.PreventUpdate()


@app.callback(Output('min_sun_elevation_init', 'children'),
              [Input('min_sun_elevation', 'value'), Input('min_sun_elevation', 'loading_state')],
              [State('min_sun_elevation_init', 'children')])
def set_min_sun_elevation(value, _, init):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if trigger == 'min_sun_elevation.value':
        if init is None:
            logger.debug('set_min_sun_elevation: init min')
            return True
        if value is None:
            logger.debug('set_gps_orientation: None value ignored')
            raise dash.exceptions.PreventUpdate()
        logger.debug('set_min_sun_elevation: ' + str(value))
        runner.min_sun_elevation = value
        runner.set_cfg_variable('Runner', 'min_sun_elevation', value)
    elif trigger == 'min_sun_elevation.loading_state':
        logger.debug('set_min_sun_elevation: loading')
    raise dash.exceptions.PreventUpdate()


@app.callback(Output('refresh_sun_elevation_init', 'children'),
              [Input('refresh_sun_elevation', 'value'), Input('refresh_sun_elevation', 'loading_state')],
              [State('refresh_sun_elevation_init', 'children')])
def set_refresh_sun_elevation(value, _, init):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if trigger == 'refresh_sun_elevation.value':
        if init is None:
            logger.debug('set_refresh_sun_elevation: init refresh')
            return True
        if value is None:
            logger.debug('set_gps_orientation: None value ignored')
            raise dash.exceptions.PreventUpdate()
        logger.debug('set_refresh_sun_elevation: ' + str(value))
        if value < 0:
            logger.debug('set_refresh_sun_elevation: invalid input' + str(value))
        runner.refresh_delay = value
        runner.set_cfg_variable('Runner', 'refresh', value)
    elif trigger == 'refresh_sun_elevation.loading_state':
        logger.debug('set_refresh_sun_elevation: loading')
    raise dash.exceptions.PreventUpdate()


@app.callback(Output("device_file_modal", "is_open"),
              [Input("trigger_device_file_modal", "n_clicks"),
               Input("device_file_modal_close", "n_clicks")],
              [State("device_file_modal", "is_open")])
def toggle_device_file_modal(n1, n2, is_open):
    if n1 or n2:
        return not is_open
    return is_open


@app.callback([Output("device_file_modal_alert_success", "is_open"),
               Output("device_file_modal_alert_fail", "is_open"),
               Output("device_file_modal_alert_fail", "children"),
               Output('select_device_file', 'options'),
               Output('select_device_file', 'value')],
              [Input("device_file_modal_update_options", "children"), Input('upload_device_file', 'contents')],
              [State('upload_device_file', 'filename'),
               State('upload_device_file', 'last_modified')])
def upload_device_file(change_option, content, filename, last_modified):
    flag_success = False
    flag_fail = False
    error_message = "Unable to import device file. "
    trigger = dash.callback_context.triggered[0]['prop_id']
    if trigger == 'upload_device_file.contents':
        if content is not None:
            path_to_file = os.path.join(runner.cfg.get('HyperSAS', 'path_to_device_files'), filename)
            logger.debug('upload_device_file: loading %s' % filename)
            try:
                write_file(path_to_file, content)
                if runner.es:
                    es_was_alive = False
                    if runner.es.alive:
                        es_was_alive = True
                        runner.es.stop()
                runner.hypersas.set_parser(path_to_file)
                if runner.es:
                    # Updating HyperSAS parser automatically updates Es parser
                    # However, the dispatcher and wavelength of the es still have to be updated manually
                    runner.es.reset_buffers()
                    runner.es.set_dispatcher()
                    runner.es.set_wavelengths()
                    if es_was_alive:
                        runner.es.start()
                runner.set_cfg_variable('HyperSAS', 'sip', path_to_file)
                flag_success = True
            except BadZipFile as e:
                logger.warning('upload_device_file: unable to load file')
                logger.warning(e)
                error_message += str(e) + ' or sip file.'
                flag_fail = True
            except Exception as e:
                logger.warning('upload_device_file: unable to load file')
                logger.warning(e)
                error_message += str(e)
                flag_fail = True
    elif trigger == 'device_file_modal_update_options.children':
        logger.debug('upload_device_file: update available/selected options')
        if not change_option:
            raise dash.exceptions.PreventUpdate()
    path_to_device_files = runner.cfg.get('HyperSAS', 'path_to_device_files')
    if not os.path.isdir(path_to_device_files):
        os.mkdir(path_to_device_files)
    try:
        # current_device_file = f'select_device_file-{os.path.basename(runner.hypersas._parser_device_file)}'
        if os.path.dirname(runner.hypersas._parser_device_file) == path_to_device_files:
            current_device_file = os.path.basename(runner.hypersas._parser_device_file)
        else:
            current_device_file = runner.hypersas._parser_device_file
    except TypeError:
        current_device_file = None
    device_file_list = [{'label': f, 'value': f} for f in os.listdir(path_to_device_files)
                        if os.path.isfile(os.path.join(path_to_device_files, f)) and f[-4:] == '.sip']
    if not device_file_list:
        device_file_list = [{'label': 'No device file available. Please upload one.', 'value': 'no-files', 'disabled': True}]
    return flag_success, flag_fail, error_message, device_file_list, current_device_file


def write_file(filename, content):
    data = content.encode("utf8").split(b";base64,")[1]
    with open(filename, "wb") as fp:
        fp.write(base64.decodebytes(data))


@app.callback([Output("device_file_modal_alert_fail_sel", "is_open"),
               Output("device_file_modal_alert_fail_sel", "children"),
               Output("device_file_modal_update_options", "children")],
              [Input('select_device_file', 'value')])
def select_device_file(filename):
    if not filename:
        raise dash.exceptions.PreventUpdate()
    path_to_file = os.path.join(runner.cfg.get('HyperSAS', 'path_to_device_files'), filename)
    if runner.hypersas._parser_device_file == path_to_file or \
        runner.hypersas._parser_device_file == filename:
        # Same value selected so no need to update
        raise dash.exceptions.PreventUpdate()
    logger.debug('select_device_file: loading %s' % filename)
    try:
        if runner.es:
            es_was_alive = False
            if runner.es.alive:
                es_was_alive = True
                runner.es.stop()
        runner.hypersas.set_parser(path_to_file)
        if runner.es:
            # Updating HyperSAS parser automatically updates Es parser
            # However, the dispatcher and wavelength of the es still have to be updated manually
            runner.es.reset_buffers()
            runner.es.set_dispatcher()
            runner.es.set_wavelengths()
            if es_was_alive:
                runner.es.start()
        runner.set_cfg_variable('HyperSAS', 'sip', path_to_file)
        # Done, raise dash prevent update outside try
    except BadZipFile as e:
        logger.warning('select_device_file: unable to load file')
        logger.warning(e)
        return True, "Unable to import device file. " + str(e) + ' or sip file.', True
    except Exception as e:
        logger.warning('select_device_file: unable to load file')
        logger.warning(e)
        return True, "Unable to import device file. " + str(e), True
    raise dash.exceptions.PreventUpdate()


##########
# Halt
@app.callback(Output("halt_modal", "is_open"),
              [Input("trigger_halt_modal", "n_clicks"), Input("halt_modal_close", "n_clicks")],
              [State("halt_modal", "is_open")])
def toggle_halt_modal(n1, n2, is_open):
    # TODO Fix React warning
    # TODO Hide modal when system is rebooted
    if n1 or n2:
        return not is_open
    return is_open


@app.callback([Output("halt_modal_body", "children"),
               Output("halt_modal_halt", "children"), Output("halt_modal_close", "className")],
              [Input("halt_modal_halt", "n_clicks")])
def halt(n_clicks):
    if n_clicks:
        return "Shutting down the system. Please wait 30 seconds before unplugging power.", \
               [dbc.Spinner(size='sm'), " Shutting Down... "], 'd-none'
    else:
        raise dash.exceptions.PreventUpdate()


@app.callback(Output("no_output_0", "children"), [Input("halt_modal_body", "children")])
def stop_pysas_and_halt_system(body):
    if body[:13] == 'Shutting down':
        logger.info('halt')
        runner.interrupt_from_ui = True
        stop_dash()
    else:
        raise dash.exceptions.PreventUpdate()


def stop_dash():
    # Stop dash environment
    #   Will stop the application and call atexit in inverse order of registration
    #   Runner atexit should call runner.stop() last in which shutdown host
    #   is called if option is specified in configuration file
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()


app.clientside_callback(
    """
    function(value) {
        if (value.includes('Shutting down')) {
            setTimeout(function() {
                var body = document.getElementById('halt_modal_body');
                body.innerHTML = "The system is down. You can safely unplug the power.";
                var btn = document.getElementById('halt_modal_halt');
                btn.innerHTML = "Down";
                btn.classList.add("disabled")
            }, 29000);
        }
        return '';
    }
    """,
    Output('no_output_2', 'children'),
    [Input('halt_modal_body', 'children')]
)


###########
# Figures
@app.callback(Output('figure_system_orientation', 'figure'),
              [Input('status_refresh_interval', 'n_intervals'),
               Input('tower_orientation', 'value'),
               Input('tower_valid_orientation_prt', 'value'), Input('tower_valid_orientation_stb', 'value')])
def update_figure_system_orientation(_, tower_orientation, tower_limit_prt, tower_limit_stb):
    timestamp = time()
    # Get Tower Orientation
    trigger = dash.callback_context.triggered[0]['prop_id']
    tower = float('nan')
    if trigger == 'tower_orientation.value':
        if tower_orientation:
            tower = tower_orientation
    else:
        tower = runner.indexing_table.position
    # Get Tower Limits
    if trigger == 'tower_valid_orientation_prt.value' or trigger == 'tower_valid_orientation_stb.value':
        if tower_limit_prt is None or tower_limit_stb is None:
            raise dash.exceptions.PreventUpdate()
        auto_pilot_limits = [tower_limit_prt, tower_limit_stb]
    else:
        auto_pilot_limits = runner.pilot.tower_limits
    # Compute blind zone to display
    if auto_pilot_limits[1] > auto_pilot_limits[0]:
        blind_zone_width = 360 - (auto_pilot_limits[1] - auto_pilot_limits[0])
    else:
        blind_zone_width = auto_pilot_limits[0] - auto_pilot_limits[1]
    blind_zone_center = auto_pilot_limits[1] + blind_zone_width / 2
    # Update telemetry in special cases
    if runner.operation_mode == 'manual' and timestamp - runner.sun_position_timestamp > runner.refresh_delay:
        # Get Sun elevation
        runner.get_sun_position()
    if runner.operation_mode == 'manual' or (runner.asleep and runner.operation_mode == 'auto'):
        # Get HyperSAS THS Compass adjusted
        if runner.heading_source != 'ths_heading' and runner.hypersas.alive:
            runner.hypersas.compass_adj = get_true_north_heading(runner.hypersas.compass,
                                                                 runner.gps.latitude, runner.gps.longitude,
                                                                 runner.gps.datetime, runner.gps.altitude)
        # Get Heading
        runner.get_ship_heading()
    # Get ship heading
    ship = float('nan')
    if timestamp - runner.ship_heading_timestamp < runner.DATA_EXPIRED_DELAY:
        ship = runner.ship_heading
        # Adjust Tower to ship referencial
        tower = ship + tower
        # Adjust blind zone to ship referencial
        blind_zone_center = ship + blind_zone_center
    # Get sun
    sun = float('nan')
    if timestamp - runner.sun_position_timestamp < runner.DATA_EXPIRED_DELAY and runner.sun_elevation > 0:
        sun = runner.sun_azimuth
    # Get HyperSAS Heading
    ths = float('nan')
    if timestamp - runner.hypersas.packet_THS_parsed < runner.DATA_EXPIRED_DELAY:
        ths = runner.hypersas.compass_adj
    # Get motion heading from GPS
    motion = float('nan')
    if timestamp - runner.gps.packet_pvt_received < runner.DATA_EXPIRED_DELAY and \
            runner.gps.speed > 1:  # speed greater than 1 m/s -> 3.6 km/h
        motion = runner.gps.heading_motion

    traces = []
    if not isnan(tower):
        traces.append(go.Scatterpolar(mode='lines+markers',
                                      r=[0, 1],
                                      theta=[0, tower],
                                      marker=dict(symbol=['circle', 'bowtie'], size=8),
                                      name='Tower',
                                      line_color='#1a76ff'))
    if not isnan(sun):
        traces.append(go.Scatterpolar(mode='lines+markers',
                                      r=[0, 1],
                                      theta=[0, sun],
                                      marker=dict(symbol=['circle', 'star'], size=8),
                                      name='Sun',
                                      line_color='orange'))
    if not isnan(ship):
        traces.append(go.Scatterpolar(mode='lines+markers',
                                      r=[0, 1],
                                      theta=[0, ship],
                                      marker=dict(symbol=['circle', 'triangle-up'], color='#000', size=8),
                                      name='Ship (Dual GPS)',
                                      line_color='black'))
    if not isnan(blind_zone_center) and not isnan(blind_zone_width):
        traces.append(go.Barpolar(r=[1],
                                  theta=[blind_zone_center],
                                  width=[blind_zone_width],
                                  opacity=0.2,
                                  marker=dict(color=['#000']),
                                  name='Blind zone'))
    if not isnan(ths):
        traces.append(go.Scatterpolar(mode='lines+markers',
                                      r=[0, 1],
                                      theta=[0, ths],
                                      marker=dict(symbol=['circle', 'bowtie'], color='#1a76ff', size=8),
                                      name='HyperSAS THS',
                                      opacity=0.3,
                                      line_color='#1a76ff'))
    if not isnan(motion):
        traces.append(go.Scatterpolar(mode='lines+markers',
                                      r=[0, 1],
                                      theta=[0, motion],
                                      marker=dict(symbol=['circle', 'triangle-up'], color='#000', size=8),
                                      name='GPS Motion',
                                      opacity=0.3,
                                      line_color='black'))
    if not traces:
        raise dash.exceptions.PreventUpdate()
    layout = go.Layout(title='System Orientation (&deg;N)',
                       legend=dict(orientation='h', yanchor='top', y=0),
                       showlegend=True,
                       polar=dict(radialaxis=dict(visible=False),
                                  angularaxis=dict(visible=True, direction='clockwise', rotation=90)),
                       autosize=True,
                       margin=dict(l=40, r=40, t=40, b=30, pad=4))
    return {'data': traces, 'layout': layout}


@app.callback(Output('figure_spectrums', 'figure'), [Input('hypersas_reading_interval', 'n_intervals')])
def update_figure_spectrum(_):
    timestamp = time()
    # Parse data
    runner.hypersas.parse_packets()
    if runner.es:
        runner.es.parse_packets()
    # Update traces
    traces = []
    if runner.hypersas.Lt is not None and timestamp - runner.hypersas.packet_Lt_parsed < runner.DATA_EXPIRED_DELAY:
        traces.append(go.Scatter(x=runner.hypersas.Lt_wavelength,
                                 y=runner.hypersas.Lt,
                                 name='Lt (&mu;W/cm<sup>2</sup>/nm/sr)',
                                 marker={'color': '#37536d'}))
    if runner.hypersas.Li is not None and timestamp - runner.hypersas.packet_Li_parsed < runner.DATA_EXPIRED_DELAY:
        traces.append(go.Scatter(x=runner.hypersas.Li_wavelength,
                                 y=runner.hypersas.Li,
                                 name='Li (&mu;W/cm<sup>2</sup>/nm/sr)',
                                 marker={'color': '#1a76ff'}))
    if runner.es:
        if runner.es.Es is not None and timestamp - runner.es.packet_Es_parsed < runner.DATA_EXPIRED_DELAY:
            traces.append(go.Scatter(x=runner.es.Es_wavelength,
                                     y=runner.es.Es,
                                     yaxis='y2',
                                     name='Es (&mu;W/cm<sup>2</sup>/nm)',
                                     marker={'color': 'orange'}))
    else:
        if runner.hypersas.Es is not None and timestamp - runner.hypersas.packet_Es_parsed < runner.DATA_EXPIRED_DELAY:
            traces.append(go.Scatter(x=runner.hypersas.Es_wavelength,
                                     y=runner.hypersas.Es,
                                     yaxis='y2',
                                     name='Es (&mu;W/cm<sup>2</sup>/nm)',
                                     marker={'color': 'orange'}))
    # Set Layout
    layout = go.Layout(
        title=core_instruments_names + ' Spectrum',
        showlegend=True,
        legend=dict(
            x=1.0,
            y=1.0,
            xanchor='right'
        ),
        margin=dict(l=50, r=50, t=40, b=40),
        xaxis=dict(title=dict(text='Wavelength (nm)'), exponentformat='power'),
        yaxis=dict(title=dict(text='Radiance (&mu;W/cm<sup>2</sup>/nm/sr)'), exponentformat='power'),
        yaxis2=dict(title=dict(text='Irradiance (&mu;W/cm<sup>2</sup>/nm)'), side="right", anchor="x", overlaying="y")
    )
    return {'data': traces, 'layout': layout}


##########
# Errors
@app.callback([Output("error_modal", "is_open"), Output("error_modal_body", "children"),
               Output("error_modal_reboot", "children"), Output("error_modal_close", "className")],
              [Input("error_modal_reboot", "n_clicks"), Input("error_modal_close", "n_clicks"),
               Input('status_refresh_interval', 'n_intervals')])
def update_error_modal(n1, n2, _):
    trigger = dash.callback_context.triggered[0]['prop_id']
    if trigger == 'status_refresh_interval.n_intervals':
        # Buffer use Queue
        if ui_log_queue.empty():
            raise dash.exceptions.PreventUpdate()
        msg = []
        while not ui_log_queue.empty():
            msg.append(html.P(ui_log_queue.get_nowait().message))
        return True, msg, 'Reboot', 'mr-1'
        # buffer use StreamIO
        # buffer = ui_log_queue.getvalue()
        # if buffer:
        #     ui_log_queue.truncate(0)
        #     ui_log_queue.seek(0)
        #     return buffer, True
        # else:
        #     return "", False
    elif trigger == 'error_modal_reboot.n_clicks':
        if n1:
            return True, "Rebooting the system. Please wait two minutes to reload page.", \
                   [dbc.Spinner(size='sm'), " Rebooting... "], 'd-none'
        raise dash.exceptions.PreventUpdate()
    elif trigger == 'error_modal_close.n_clicks':
        if n2:
            return False, "", "Reboot", 'mr-1'
        raise dash.exceptions.PreventUpdate()
    else:
        logger.debug('unexpected case')
        raise dash.exceptions.PreventUpdate()


@app.callback(Output("no_output_1", "children"), [Input("error_modal_reboot", "children")])
def reboot(button_value):
    if button_value[1] == ' Rebooting... ':
        logger.info('reboot')
        runner.reboot_from_ui = True
        stop_dash()
    raise dash.exceptions.PreventUpdate()
