import base64
import logging
import os
import shutil
import signal
import sys
from datetime import datetime
from math import isnan
from time import gmtime, strftime, time
from urllib import request
from zipfile import BadZipFile

import numpy as np
import dash
from dash import Input, Output, State, dcc, html, no_update, Patch
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objs as go
from plotly.io import templates as pio_templates
from pySatlantic.instrument import Instrument as pySat

from pySAS import __version__, CFG_FILENAME, ui_log_queue
from pySAS.runner import Runner, get_true_north_heading


STATUS_REFRESH_INTERVAL = 1000
HYPERSAS_READING_INTERVAL = 2000


logger = logging.getLogger('ui')

runner = Runner(CFG_FILENAME)

app = dash.Dash(
    '__main__',
    title= "pySAS v" + __version__, update_title=None,
    # external_stylesheets=[dbc.themes.BOOTSTRAP],  # Offline in assets folder
    # assets_folder='assets',
    # these meta_tags ensure content is scaled correctly on different devices
    # see: https://www.w3schools.com/css/css_rwd_viewport.asp for more
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"}
    ],
)


####################
# Sidebar / Navbar #
####################


sidebar = html.Div([
        # Sidebar header
        dbc.Row([
            dbc.Col(html.H2("pySAS v" + __version__, id='title', className="display-4", style={'fontSize': '3.0rem'})),
            dbc.Col([
                html.Button(
                    html.Span(className="navbar-toggler-icon"), className="navbar-toggler", id="navbar-toggle",
                    style={"color": "rgba(0,0,0,.5)", "border-color": "rgba(0,0,0,.1)"},
                ),
                html.Button(
                    html.Span(className="navbar-toggler-icon"), className="navbar-toggler", id="sidebar-toggle",
                    style={"color": "rgba(0,0,0,.5)", "border-color": "rgba(0,0,0,.1)"},
                ),
            ], width="auto", align="center"),
        ]),
        # use the Collapse component to animate hiding / revealing things
        dbc.Collapse([
            # Clock
            html.H3([html.Span("17:34:04", id='time'), " UTC"],
                    style={'fontFamily': 'Menlo'}, className='text-center mb-0 mt-4'),
            html.H3('Nov 26, 2019', id='date', style={'fontFamily': 'Menlo'}, className='text-center mb-3'),
            # html.Hr(),

            # Control Menu
            html.Div([
                dbc.Row([
                    dbc.Label("Mode", html_for="operation_mode", width=4),
                    dbc.Col(dcc.Dropdown(id='operation_mode', value='auto', searchable=False, clearable=False,
                                         options=[{'label': "Manual", 'value': 'manual'},
                                                  {'label': "Auto", 'value': 'auto'}]), width=8),
                ], className="mt-5 mb-3"),
                dbc.Row([
                    dbc.Label(runner.core_instrument_name, html_for="hypersas_switch", width=6),
                    dbc.Col([
                        dbc.Switch(id="hypersas_switch", value=False, className='mt-2 ms-1 d-inline-block')],
                            width=6, className="text-end"),
                ], className="mt-5 mb-3"),
                dbc.Row([
                    dbc.Label("GPS", html_for="gps_switch", width=3),
                    dbc.Col([
                        dbc.Badge('No Fix', id='gps_flag_fix', color='danger', pill=True,
                                  style={'lineHeight': 0.72}, className='mt-2 me-2'),
                        dbc.Badge('No Hdg', id='gps_flag_hdg', color='warning', pill=True,
                                  style={'lineHeight': 0.72}, className='mt-2 me-2'),
                        dbc.Badge('No Time', id='gps_flag_time', color='danger', pill=True,
                                  style={'lineHeight': 0.72}, className='mt-2 me-2'),
                        dbc.Switch(id="gps_switch", value=False, className='mt-2 ms-1 d-inline-block')],
                            width=9, className="text-end"),
                ], className="mb-3"),
                dbc.Row([
                    dbc.Label("Tower", id='tower_label', html_for="tower_switch", width=4),
                    dbc.Col([
                        dbc.Badge('Stalled', id='tower_stall_flag', color='danger', pill=True,
                                  style={'lineHeight': 0.72}, href="#", className='d-none'),  #mt-2 me-2 text-decoration-none
                        dbc.Badge('Zero', id='tower_zero', color='secondary', pill=True,
                                  style={'lineHeight': 0.72}, href="#", className='mt-2 me-2 text-decoration-none'),
                        dbc.Switch(id="tower_switch", value=False, className='mt-2 ms-1 d-inline-block')],
                            width=8, className="text-end"),
                ], className="mb-3"),
                html.Div([
                    dcc.Slider(
                        id='tower_orientation', min=-180, max=180, step=1, value=96,
                        included=False, disabled=False,
                        marks={i: '{}°'.format(i) for i in [-160, -80, 0, 80, 160]},
                        tooltip={'always_visible': False, 'placement': 'bottom'},
                        # className='d-none',
                    )
                ], className='mb-3')

            ], style={'textAlign': 'left'}),
            # html.Hr(),

            # Buttons
            dbc.Row([
                dbc.Col(dbc.Button("Sync. Clock", color="dark", outline=True, id='set_clock'),
                        width=5, class_name='d-grid'),
                dbc.Col(dbc.Button("Settings", color="dark", outline=True, id='open_settings_modal'),
                        width=4, class_name='d-grid gap-2'),
                dbc.Col(dbc.Button("Halt", color="secondary", outline=True, id='open_halt_modal'),
                        width=3, class_name='d-grid gap-2'),
            ], className='mt-5 mb-3'),
        ], id="collapse"),
], id="sidebar")


@app.callback(
    Output("sidebar", "className"),
    [Input("sidebar-toggle", "n_clicks")],
    [State("sidebar", "className")],
)
def toggle_classname(n, classname):
    if n and classname == "":
        return "collapsed"
    return ""


@app.callback(
    Output("collapse", "is_open"),
    [Input("navbar-toggle", "n_clicks")],
    [State("collapse", "is_open")],
)
def toggle_collapse(n, is_open):
    if n:
        return not is_open
    return is_open


@app.callback(Output('operation_mode', 'value'), Input('load_content', 'n_clicks'))
def init(_):
    if _ is not None:
        raise PreventUpdate
    return runner.operation_mode


@app.callback([Output('time', 'children'), Output('date', 'children')],
              [Input('status_refresh_interval', 'n_intervals')])
def get_time(_):
    dt = gmtime()
    return strftime("%-H:%M:%S", dt), strftime("%b %d, %Y", dt)


@app.callback(Output('hypersas_switch', 'disabled'), Output('gps_switch', 'disabled'),
              Output('tower_switch', 'disabled'), Output('tower_zero', 'className'),
              Output('tower_orientation', 'className'), Output('tower_orientation', 'value', allow_duplicate=True),
              Input('operation_mode', 'value'), prevent_initial_call=True)
def set_operation_mode(mode):
    if mode not in ['auto', 'manual']:
        logger.warning('set_operation_mode: invalid operation mode ' + str(mode))
        raise dash.exceptions.PreventUpdate()
    # Switch runner operation mode
    if runner.operation_mode != mode:
        runner.operation_mode = mode  # automatically stop previous mode and start new mode thread
        runner.set_cfg_variable('Runner', 'operation_mode', mode)
    # Update user interface
    disable_switch = mode == 'auto'
    hide_tower_zero = 'd-none' if mode == 'auto' else 'mt-2 me-2 text-decoration-none'
    hide_tower_orientation = 'd-none' if mode == 'auto' else ''
    tower_orientation = no_update if mode == 'auto' else runner.indexing_table.position
    return disable_switch, disable_switch, disable_switch, hide_tower_zero, hide_tower_orientation, tower_orientation


@app.callback(Output('hypersas_switch', 'value'), Output('gps_switch', 'value'), Output('tower_switch', 'value'),
              Input('status_refresh_interval', 'n_intervals'),
              State('hypersas_switch', 'value'), State('gps_switch', 'value'), State('tower_switch', 'value'))
def get_switches(_, hypersas_switch, gps_switch, tower_switch):
    hypersas = no_update if runner.hypersas.alive == hypersas_switch or runner.hypersas.busy else runner.hypersas.alive
    gps = no_update if runner.gps.alive == gps_switch or runner.gps.busy else runner.gps.alive
    tower = no_update if runner.indexing_table.alive == tower_switch or runner.indexing_table.busy else runner.indexing_table.alive
    if hypersas == no_update and gps == no_update and tower == no_update:
        raise PreventUpdate
    return hypersas, gps, tower


@app.callback(Output('no_output', 'children', allow_duplicate=True),
              Input('hypersas_switch', 'value'),
              prevent_initial_call=True)
def set_hypersas_switch(switch):
    if runner.hypersas.busy:
        logger.debug('set_hypersas_switch: busy')
        raise PreventUpdate
    if switch != runner.hypersas.alive:
        runner.hypersas.busy = True
        if switch:
            logger.debug('set_hypersas_switch: start')
            if runner.imu:
                runner.imu.start()
            if runner.es:
                runner.es.start()
            runner.hypersas.start()
            runner.gps.start_logging()  # Must start after hypersas otherwise Runner.run_manual could stop GPS logging
        else:
            logger.debug('set_hypersas_switch: stop')
            runner.hypersas.stop()
            if runner.es:
                runner.es.stop()
            if runner.imu:
                runner.imu.stop()
            runner.gps.stop_logging()


@app.callback(Output('no_output', 'children', allow_duplicate=True),
              Input('gps_switch', 'value'),
              prevent_initial_call=True)
def set_gps_switch(switch):
    if runner.gps.busy:
        logger.debug('set_gps_switch: busy')
        raise PreventUpdate
    if switch != runner.gps.alive:
        runner.gps.busy = True
        if switch:
            logger.debug('set_gps_switch: start')
            runner.gps.start()
        else:
            logger.debug('set_gps_switch: stop')
            runner.gps.stop()


@app.callback([Output('gps_flag_hdg', 'children'), Output('gps_flag_hdg', 'color'), Output('gps_flag_hdg', 'className'),
               Output('gps_flag_fix', 'children'), Output('gps_flag_fix', 'color'), Output('gps_flag_fix', 'className'),
               Output('gps_flag_time', 'className')],
              [Input('status_refresh_interval', 'n_intervals')])
def get_gps_flags(_):
    if not runner.gps.alive:
        return no_update, no_update, 'd-none', \
               no_update, no_update, 'd-none', \
               'd-none'
    # Heading
    if runner.gps.fix_type < 2:
        hdg = 'No Hdg', 'warning', 'd-none'
    elif time() - runner.gps.packet_relposned_received > runner.DATA_EXPIRED_DELAY:
        hdg = 'No Hdg', 'warning', 'mt-2 me-2'
    elif runner.gps.heading_valid:
        hdg = 'Hdg', 'success', 'mt-2 me-2'
    else:
        hdg = 'No Hdg', 'danger', 'mt-2 me-2'
    # Fix
    if time() - runner.gps.packet_pvt_received > runner.DATA_EXPIRED_DELAY:
        fix = 'Off', 'warning', 'mt-2 me-2'
    elif runner.gps.fix_type == 0:
        fix = 'No Fix', 'danger', 'mt-2 me-2'
    elif runner.gps.fix_type == 1:  # Dead reckoning
        fix = 'DR', 'warning', 'mt-2 me-2'
    elif runner.gps.fix_type == 2:
        fix = '2D-Fix', 'info', 'mt-2 me-2'
    elif runner.gps.fix_type == 3:
        fix = '3D-Fix', 'success', 'mt-2 me-2'
    elif runner.gps.fix_type == 4:
        fix = 'GNSS+DR', 'info', 'mt-2 me-2'
    elif runner.gps.fix_type == 5:
        fix = 'Time Only', 'warning', 'mt-2 me-2'
    else:
        fix = 'Unknown', 'danger', 'mt-2 me-2'
    # Time
    if runner.gps.datetime_valid:
        dt = 'd-none',
    else:
        dt = 'mt-2 me-2',
    return hdg + fix + dt


@app.callback(Output('no_output', 'children', allow_duplicate=True),
              Input('tower_switch', 'value'),
              prevent_initial_call=True)
def set_tower_switch(switch):
    if runner.indexing_table.busy:
        logger.debug('set_tower_switch: busy')
        raise PreventUpdate
    if switch != runner.indexing_table.alive:
        runner.indexing_table.busy = True
        if switch:
            logger.debug('set_tower_switch: start')
            runner.indexing_table.start()
        else:
            logger.debug('set_tower_switch: stop')
            runner.indexing_table.stop()


@app.callback(Output('tower_orientation', 'value', allow_duplicate=True),
              Input('tower_zero', 'n_clicks'),
              prevent_initial_call=True)
def set_tower_zero(_):
    logger.debug('set_tower_zero: zeroed')
    runner.indexing_table.reset_position_zero()
    return runner.indexing_table.position  # Keep old position if failed


@app.callback(Output('tower_stall_flag', 'className', allow_duplicate=True),
              Input('tower_stall_flag', 'n_clicks'),
              prevent_initial_call=True)
def set_tower_stall_flag(_):
    if runner.indexing_table.stalled:
        runner.indexing_table.reset_stall_flag()
        return 'd-none'
    raise PreventUpdate


@app.callback(Output('tower_stall_flag', 'className', allow_duplicate=True),
              Input('status_refresh_interval', 'n_intervals'),
              State('tower_stall_flag', 'className'),
              prevent_initial_call=True)
def get_tower_stall_flag(_, state):
    if runner.indexing_table.alive and (state != 'd-none') != runner.indexing_table.stalled:
        return 'mt-2 me-2 text-decoration-none' if runner.indexing_table.stalled else 'd-none'
    raise PreventUpdate


@app.callback(Output('no_output', 'children', allow_duplicate=True),
              Input('tower_orientation', 'value'), prevent_initial_call=True)
def set_tower_orientation(value):
    if runner.indexing_table.alive:
        runner.indexing_table.set_position(value)
        logger.debug(f'set_tower_orientation: {value}')
    else:
        logger.warning('set_tower_orientation: unable, tower not alive')


@app.callback(Output('tower_label', 'children'),
              Input('status_refresh_interval', 'n_intervals'))
def get_tower_orientation(_):
    if runner.indexing_table.alive:
        return f'Tower {runner.indexing_table.position:.1f}°' # if not isnan(runner.indexing_table.position) else 'Tower'
    raise PreventUpdate


##################
# Settings Modal #
##################


settings_modal = dbc.Modal([
    dbc.ModalHeader(dbc.ModalTitle("pySAS Settings")),
    dbc.ModalBody([
        html.Div([
            dbc.Label("GPS Orientation", html_for="gps_orientation"),
            dbc.InputGroup([
                dbc.Input(id='gps_orientation', type='number', min=-180, max=360, step=1, class_name='text-end'),
                dbc.InputGroupText("°")
            ]),
            dbc.FormText('Difference in heading between the GPS and the ship. '
                         'For details, see schematics inside the pySAS controller box.', color='muted'),
        ], className="mb-3"),
        dbc.Row([
            dbc.Label("Tower Orientation Range", html_for="tower_valid_orientation_prt"),
            dbc.Col(
                dbc.InputGroup([
                    dbc.InputGroupText("Port side"),
                    dbc.Input(id='tower_valid_orientation_prt', type='number', min=-180, max=360, step=1, class_name='text-end'),
                    dbc.InputGroupText("°")
                ]), width=6, sm=6, xs=12,
            ),
            dbc.Col(
                dbc.InputGroup([
                    dbc.InputGroupText("Starboard"),
                    dbc.Input(id='tower_valid_orientation_stb', type='number', min=-180, max=360, step=1, class_name='text-end'),
                    dbc.InputGroupText("°")
                ]), width=6, sm=6, xs=12,
            ),
            dbc.FormText('The orientation range within which pySAS can collect valid measurements. '
                         'The orientation range is with respect to the tower zero, '
                         'which is commonly aligned with the ship heading. '
                         'Outside this range the pySAS would be pointing at the ship or its wake. '
                         'The shaded area on the system orientation chart depicts the no measurements range.',
                         color='muted'),
        ], className="mb-3"),
        html.Div([
            dbc.Label("Optimal Sensors\' Azimuth", html_for="optimal_sensors_azimuth"),
            dbc.InputGroup([
                dbc.Input(id='optimal_sensors_azimuth', type='number', min=-180, max=360, step=1, class_name='text-end'),
                dbc.InputGroupText("°")
            ]),
            dbc.FormText('Optimal sensors\' azimuth with respect to the sun. '
                         'In other words, the horizontal angle between the sun and the sensors\' viewing direction (Lt & Li). '
                         'Typically between 90° and 135°. Mobley 1999 recommends 135°.', color='muted'),
        ], className="mb-3"),
        dbc.Row([
            dbc.Label("Sensors\' Azimuth Limits", html_for="sensors_azimuth_min"),
            dbc.Col(
                dbc.InputGroup([
                    dbc.InputGroupText("Min"),
                    dbc.Input(id='sensors_azimuth_min', type='number', min=-180, max=360, step=1, class_name='text-end'),
                    dbc.InputGroupText("°")
                ]), width=6, sm=6, xs=12,
            ),
            dbc.Col(
                dbc.InputGroup([
                    dbc.InputGroupText("Max"),
                    dbc.Input(id='sensors_azimuth_max', type='number', min=-180, max=360, step=1, class_name='text-end'),
                    dbc.InputGroupText("°")
                ]), width=6, sm=6, xs=12,
            ),
            dbc.FormText('Acceptable range of sensors azimuth with respect to the sun for which pySAS can take measurements. '
                         'If the optimal sensors azimuth can not be achieved, '
                         'pySAS will set the tower to the closest viewing angle within the range specified. '
                         'If no azimuth can be achieved within the specified range, '
                         'pySAS will not record measurements (turn off radiometers and tower). '
                         'Typical, sensor azimuth range is 90° to 135°.',
                         color='muted'),
        ], className="mb-3"),
        html.Div([
            dbc.Label("Sun Elevation", html_for='min_sun_elevation'),
            dbc.InputGroup([
                dbc.InputGroupText("Min"),
                dbc.Input(id='min_sun_elevation', type='number', min=0, max=90, step=1),
                dbc.InputGroupText("°")
            ]),
            dbc.FormText('If sun elevation is lower than the specified value, pySAS stop taking measurements. '
                         'Sun_elevation = 90 - Sun_zenith', color='muted'),
        ], className='mb-3'),
        html.Div([
            dbc.Label("Refresh Period", html_for='refresh_period'),
            dbc.InputGroup([
                dbc.Input(id='refresh_period', type='number', min=0.01, max=300, step=0.5),
                dbc.InputGroupText("s")
            ]),
            dbc.FormText('Period at which adjust and log tower position. '
                         'Typical values are between 1 and 5 seconds.', color='muted'),
        ], className='mb-3'),
        dbc.Row([
            dbc.Label('Select Calibration File:', html_for='select_device_file'),
            dbc.Col(
                dbc.RadioItems(id='select_device_file', labelCheckedStyle={"color": "green"},
                               options=['Device 1', 'Device 2', 'Device 3']),
                width=6, sm=6, xs=12,
            ),
            dbc.Col(
                dcc.Upload(
                    id='upload_device_file', children=html.Div([
                        'Drag and Drop or ', html.A('Select Device Files', style={'color': '#007bff', 'cursor': 'pointer'})
                    ]), style={'padding': '40px 30px', 'borderWidth': '1px', 'borderStyle': 'dashed',
                               'borderRadius': '5px', 'textAlign': 'center'}, className='m-1',
                ), width=6, sm=6, xs=12,
            ),
            dbc.FormText('Updating calibration file requires you to reload page in web browser.',
                         color='muted', class_name='mb-3'),
        ]),
        html.Div([
            dbc.Alert("Settings alert.", id='settings_modal_alert', is_open=False, color="primary", dismissable=False)
        ], className='mb-3'),
    ]),
    dbc.ModalFooter([
        dbc.Button("Cancel", id="settings_modal_cancel", color='secondary', n_clicks=0),
        dbc.Button("Save", id="settings_modal_save", color='primary', n_clicks=0),
    ]),
], is_open=False, id="settings_modal", centered=True, backdrop="static")


@app.callback(Output('settings_modal', 'is_open', allow_duplicate=True),
              Input('open_settings_modal', 'n_clicks'),
              Input('settings_modal_cancel', 'n_clicks'),
              State('settings_modal', 'is_open'),
              prevent_initial_call=True)
def toggle_settings_modal(open_modal, close_modal, is_open):
    return not is_open


@app.callback(Output('tower_valid_orientation_prt', 'value'), Output('tower_valid_orientation_stb', 'value'),
              Output('gps_orientation', 'value'),
              Output('optimal_sensors_azimuth', 'value'),
              Output('sensors_azimuth_min', 'value'), Output('sensors_azimuth_max', 'value'),
              Output('min_sun_elevation', 'value'),
              Output('refresh_period', 'value'),
              Output('select_device_file', 'options'), Output('select_device_file', 'value'),
              Output('settings_modal_alert', 'color', allow_duplicate=True),
              Output('settings_modal_alert', 'is_open', allow_duplicate=True),
              Input('settings_modal', 'is_open'), prevent_initial_call=True)
def get_settings(is_open):
    if not is_open:
        raise PreventUpdate
    # Get device file used
    device_file_options, current_device_file = get_device_file_options()
    # Other parameters
    return (*runner.pilot.tower_limits, runner.pilot.compass_zero,
            runner.pilot.target, *runner.pilot.target_limits,
            runner.min_sun_elevation, runner.refresh_delay,
            device_file_options, current_device_file, 'light', False)


@app.callback(Output('settings_modal_alert', 'is_open'), Output('settings_modal_alert', 'children'),
              Output('settings_modal_alert', 'color'), Output('settings_modal_alert', 'duration'),
              Output('fig_spectrum_cache', 'data', allow_duplicate=True),
              Output('fig_timeseries_cache', 'data', allow_duplicate=True),
              Input('settings_modal_save', 'n_clicks'),
              State('tower_valid_orientation_prt', 'value'), State('tower_valid_orientation_stb', 'value'),
              State('gps_orientation', 'value'),
              State('optimal_sensors_azimuth', 'value'),
              State('sensors_azimuth_min', 'value'), State('sensors_azimuth_max', 'value'),
              State('min_sun_elevation', 'value'),
              State('refresh_period', 'value'), State('select_device_file', 'value'),
              prevent_initial_call=True)
def save_settings(save_click, prt, stb, gps, optimal_az, min_az, max_az, sun, period, device_file):
    if not save_click:
        raise PreventUpdate
    # Reset figures cache
    fig_spectrum_cache, fig_timeseries_cache = None, None
    # Check Input
    if gps is None or gps < -180 or gps > 360:
        return True, 'Invalid gps orientation. Acceptable range -180 to 360.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if prt is None or stb is None or prt < -180 or prt > 360 or stb < -180 or stb > 360:
        return True, 'Invalid tower orientation range. Acceptable range -180 to 360.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if optimal_az is None or optimal_az < -180 or sun > 360:
        return True, 'Invalid optimal sensors\' azimuth. Acceptable range -180 to 360.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if min_az is None or max_az is None or min_az < -180 or min_az > 360 or max_az < -180 or max_az > 360:
        return True, 'Invalid sensors\' azimuth limits. Acceptable range -180 to 360.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if min_az > max_az:
        return True, 'Invalid sensors\' azimuth limits. Min should be lower than Max.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if optimal_az < min_az or max_az < optimal_az:
        return True, 'Optimal sensors\' azimuth is outside limits.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if sun is None or sun < 0 or sun > 90:
        return True, 'Invalid min sun elevation. Acceptable range 0 to 90.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    if period is None or period < 0.1 or period > 600:
        return True, 'Invalid refresh period. Acceptable range 0.1 to 600.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    # Check Device File
    path_to_file = os.path.join(runner.cfg.get('HyperSAS', 'path_to_device_files'), device_file)
    if not (runner.hypersas._parser_device_file == path_to_file or
            runner.hypersas._parser_device_file == device_file):
        logger.debug(f'select_device_file: loading {device_file}')
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
            # IMU doesn't need to be updated as parser is hardcoded
        except BadZipFile as e:
            logger.warning('select_device_file: unable to load file')
            logger.warning(e)
            return True, "Unable to import device file. " + str(e) + ' or sip file.', 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
        except Exception as e:
            logger.warning('select_device_file: unable to load file')
            logger.warning(e)
            return True, "Unable to import device file. " + str(e), 'danger', 3600000, fig_spectrum_cache, fig_timeseries_cache
    # Save Other settings
    runner.pilot.set_tower_limits([prt, stb])
    runner.set_cfg_variable('AutoPilot', 'valid_indexing_table_orientation_limits', [prt, stb])
    runner.pilot.target = optimal_az
    runner.set_cfg_variable('AutoPilot', 'optimal_angle_away_from_sun', optimal_az)
    runner.pilot.set_target_limits([min_az, max_az])
    runner.set_cfg_variable('AutoPilot', 'valid_angle_away_from_sun_limits', [min_az, max_az])
    runner.pilot.compass_zero = gps
    runner.set_cfg_variable('AutoPilot', 'gps_orientation_on_ship', gps)
    runner.min_sun_elevation = sun
    runner.set_cfg_variable('Runner', 'min_sun_elevation', sun)
    runner.refresh_delay = period
    runner.set_cfg_variable('Runner', 'refresh', period)
    return True, 'Settings saved.', 'success', 1500, fig_spectrum_cache, fig_timeseries_cache


@app.callback(Output('settings_modal_alert', 'is_open', allow_duplicate=True),
              Output('settings_modal_alert', 'children', allow_duplicate=True),
              Output('settings_modal_alert', 'color', allow_duplicate=True),
              Output('settings_modal_alert', 'duration', allow_duplicate=True),
              Output('select_device_file', 'options', allow_duplicate=True),
              Output('select_device_file', 'value', allow_duplicate=True),
              Input('upload_device_file', 'contents'),
              State('upload_device_file', 'filename'), State('upload_device_file', 'last_modified'),
              prevent_initial_call=True)
def upload_device_file(contents, filename, last_modified):
    device_file_options, device_file_selected = no_update, no_update
    if contents is not None:
        tmp_dir = os.path.join(runner.cfg.get('HyperSAS', 'path_to_device_files'), 'tmp')
        try:
            logger.debug('upload_device_file: loading %s' % filename)
            # Download and check file in tmp directory
            if not os.path.isdir(tmp_dir):
                os.mkdir(tmp_dir)
            tmp_file = os.path.join(tmp_dir, filename)
            write_file(tmp_file, contents)
            pySat(tmp_file)
            # File passed check, hence move to device files directory
            os.rename(tmp_file, os.path.join(runner.cfg.get('HyperSAS', 'path_to_device_files'), filename))
            message, color = 'Device file uploaded.', 'success'
            # Update device file options and select uploaded file
            device_file_options, device_file_selected = get_device_file_options(False), filename
        except Exception as e:
            logger.warning('upload_device_file: unable to load file')
            logger.warning(e)
            message, color = "Unable to import device file. " + str(e), 'warning'
        shutil.rmtree(tmp_dir)
    else:
        message, color = 'No file uploaded.', 'info'
    return True, message, color, 3600000, device_file_options, device_file_selected


def write_file(filename, content):
    data = content.encode("utf8").split(b";base64,")[1]
    with open(filename, "wb") as fp:
        fp.write(base64.decodebytes(data))


def get_device_file_options(and_current=True):
    path_to_device_files = runner.cfg.get('HyperSAS', 'path_to_device_files')
    if not os.path.isdir(path_to_device_files):
        os.mkdir(path_to_device_files)
    # Get device file options
    device_file_list = [{'label': f, 'value': f} for f in os.listdir(path_to_device_files)
                        if os.path.isfile(os.path.join(path_to_device_files, f)) and f[-4:] == '.sip']
    if not device_file_list:
        device_file_list = [
            {'label': 'No device file available. Please upload one.', 'value': 'no-files', 'disabled': True}
        ]
    if not and_current:
        return device_file_list
    # Get device file used
    try:
        # current_device_file = f'select_device_file-{os.path.basename(runner.hypersas._parser_device_file)}'
        if os.path.dirname(runner.hypersas._parser_device_file) == path_to_device_files:
            current_device_file = os.path.basename(runner.hypersas._parser_device_file)
        else:
            current_device_file = runner.hypersas._parser_device_file
    except TypeError:
        current_device_file = None
    return device_file_list, current_device_file


@app.callback(Output('settings_modal', 'is_open', allow_duplicate=True),
              Input('settings_modal_alert', 'is_open'), State('settings_modal_alert', 'color'),
              prevent_initial_call=True)
def close_settings_modal(alert_is_open, alert_color):
    if not alert_is_open and alert_color == 'success':
        return False
    raise PreventUpdate


###############
# Clock Modal #
###############


clock_sync_modal = dbc.Modal([
    dbc.ModalBody("Clock Synchronization", id="clock_modal_body"),
    dbc.ModalFooter(dbc.Button("Close", id="clock_modal_close", color='secondary', n_clicks=0)),
], is_open=False, id="clock_modal", centered=True, backdrop="static")


@app.callback(Output('clock_modal', 'is_open'),
              Input('set_clock', 'n_clicks'),
              Input('clock_modal_close', 'n_clicks'),
              State('clock_modal', 'is_open'),
              prevent_initial_call=True)
def toggle_clock_modal(open_modal, close_modal, is_open):
    return not is_open


@app.callback(Output('clock_modal_body', 'children'),
              Input('set_clock', 'n_clicks'),
              prevent_initial_call=True)
def set_clock(set_clock_click):
    pre_sync = strftime("%Y/%m/%d %H:%M:%SZ", gmtime())
    synchronized = runner.get_time_sync()
    post_sync = strftime("%Y/%m/%d %H:%M:%SZ", gmtime())
    if synchronized:
        msg = f'Synchronize SBC with GPS clock from {pre_sync} to {post_sync}'
    else:
        msg = f'Unable to synchronize time, is the GPS on with a valid fix?'
    logger.debug(msg)
    return msg, True


###############
# Halt Modal #
###############


halt_modal = dbc.Modal([
    dbc.ModalBody("Are you sure you want to shut down pySAS now ?", id="halt_modal_body"),
    dbc.ModalFooter([
        dbc.Button("Cancel", id="halt_modal_cancel", color='secondary', n_clicks=0),
        dbc.Button("Shut Down", id="halt_modal_shutdown", color='primary', n_clicks=0),
    ]),
], is_open=False, id="halt_modal", centered=True, backdrop="static")


@app.callback(Output('halt_modal', 'is_open'),
              Input('open_halt_modal', 'n_clicks'),
              Input('halt_modal_cancel', 'n_clicks'),
              State('halt_modal', 'is_open'),
              prevent_initial_call=True)
def toggle_halt_modal(open_modal, cancel_modal, is_open):
    return not is_open


@app.callback(Output("halt_modal_body", "children"),
              Output("halt_modal_shutdown", "children"), Output("halt_modal_shutdown", "disabled"),
              Output("halt_modal_cancel", "className"),
              Input("halt_modal_shutdown", "n_clicks"),
              prevent_initial_call=True)
def halt(n_clicks):
    if n_clicks:
        return "Shutting down the system. Please wait 30 seconds before disconnecting power.", \
               [dbc.Spinner(size='sm'), " Shutting Down... "], True, 'd-none'
    else:
        raise dash.exceptions.PreventUpdate()


@app.callback(Output("no_output", "children", allow_duplicate=True), Input("halt_modal_body", "children"),
              prevent_initial_call=True)
def stop_pysas_and_halt_system(body):
    if body[:13] == 'Shutting down':
        logger.info('halt')
        runner.interrupt_from_ui = True
        stop_app()
    else:
        raise dash.exceptions.PreventUpdate()


def stop_app():
    # Stop dash environment
    #   Will stop the application and call atexit in inverse order of registration
    #   Runner atexit should call runner.stop() last in which shutdown host
    #   is called if option is specified in configuration file
    os.kill(os.getpid(), signal.SIGINT)


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
    Output('no_output_client', 'children'), Input('halt_modal_body', 'children')
)


###############
# Error Modal #
###############


error_modal = dbc.Modal([
    dbc.ModalBody("Unknown error.", id="error_modal_body"),
    dbc.ModalFooter([
        dbc.Button("Ignore", id="error_modal_ignore", color='secondary', n_clicks=0),
        dbc.Button("Reboot", id="error_modal_reboot", outline=True, color='dark', n_clicks=0),
    ]),
], is_open=False, id="error_modal", centered=True, backdrop="static")


@app.callback(Output('error_modal', 'is_open', allow_duplicate=True),
              Input('error_modal_ignore', 'n_clicks'),
              State('error_modal', 'is_open'),
              prevent_initial_call=True)
def toggle_error_modal(ignore_modal, is_open):
    return not is_open


@app.callback(Output('error_modal', 'is_open', allow_duplicate=True),
              Output("error_modal_body", "children"),
              Input('status_refresh_interval', 'n_intervals'),
              prevent_initial_call=True)
def update_error_modal(n_intervals):
    # Bug prevents to display first error message...
    if ui_log_queue.empty():
        raise PreventUpdate
    msg = []
    while not ui_log_queue.empty():
        msg.append(html.P(ui_log_queue.get_nowait().message))
    return True, msg


@app.callback(Output("error_modal_reboot", "children"), Output("error_modal_reboot", "disabled"),
              Input('error_modal_reboot', 'n_clicks'),
              prevent_initial_call=True)
def error_modal_reboot(_):
    return [dbc.Spinner(size='sm'), " Rebooting... "], True


@app.callback(Output("no_output", "children"), Input("error_modal_reboot", "children"), prevent_initial_call=True)
def reboot(button_value):
    if len(button_value) == 2 and button_value[1] == ' Rebooting... ':
        logger.info('reboot')
        runner.reboot_from_ui = True
        stop_app()
    raise PreventUpdate


###########
# Figures #
###########

graph_config = {'displaylogo': False, 'editable': False, 'displayModeBar': True, 'showTips': False,
                'modeBarButtonsToRemove': ['lasso2d', 'toImage', 'zoom', 'pan', 'select', 'zoomIn', 'zoomOut', 'resetScale']}   # 'autoScale',

plotly_template = pio_templates["simple_white"]
plotly_template.layout.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", "Noto Sans", "Liberation Sans", Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji"'
plotly_template.layout.xaxis.mirror = True
plotly_template.layout.xaxis.exponentformat = 'power'
plotly_template.layout.yaxis.mirror = True
plotly_template.layout.yaxis.exponentformat = 'power'
# plotly_template.layout.legend.bordercolor = '#0A359F'
# plotly_template.layout.legend.borderwidth = 1
pio_templates.default = plotly_template

fig = go.Figure()
ship_id = 0
fig.add_scatterpolar(r=[0, 1], theta=[0, 0], name='Ship (Dual GPS)', line_color='black',
                     mode='lines+markers', marker=dict(symbol=['circle', 'bowtie'], color='black', size=8),
                     visible=False)
blind_zone_id = 1
fig.add_barpolar(r=[1], theta=[180], width=[10], name='Blind zone', opacity=0.2, marker_color='black')
tower_id = 2
fig.add_scatterpolar(r=[0, 1], theta=[0, 0], name='Tower', line_color='#1a76ff',
                     mode='lines+markers', marker=dict(symbol=['circle', 'bowtie'], size=8),
                     visible=False)
sun_id = 3
fig.add_scatterpolar(r=[0, 1], theta=[0, 0], name='Sun', line_color='orange',
                     mode='lines+markers', marker=dict(symbol=['circle', 'star'], size=8),
                     visible=False)
ths_id = 4
fig.add_scatterpolar(r=[0, 1], theta=[0, 0], name='HyperSAS THS',  line_color='#1a76ff', opacity=0.3,
                     mode='lines+markers', marker=dict(symbol=['circle', 'bowtie'], color='#1a76ff', size=8),
                     visible=False)
imu_id = 5
fig.add_scatterpolar(r=[0, 1], theta=[0, 0], name='IMU',  line_color='black', opacity=0.3,
                     mode='lines+markers', marker=dict(symbol=['circle', 'triangle-up'], color='black', size=8),
                     visible=False)
gps_motion_id = 6
fig.add_scatterpolar(r=[0, 1], theta=[0, 0], name='GPS Motion',  line_color='black', opacity=0.3,
                     mode='lines+markers', marker=dict(symbol=['circle', 'triangle-up'], color='black', size=8),
                     visible=False)
fig.update_layout(
    title='System Orientation (&deg;N)', title_x=0.5,
    legend=dict(orientation='h', yanchor='top', y=0), showlegend=True,
    polar=dict(radialaxis=dict(visible=False), angularaxis=dict(visible=True, direction='clockwise', rotation=90)),
    autosize=True, margin=dict(l=60, r=60, t=80, b=30, pad=4)
)
fig_system_orientation = fig


@app.callback(Output('fig_system_orientation', 'figure'),
              Input('status_refresh_interval', 'n_intervals'),
              Input('tower_orientation', 'value'),
              Input('settings_modal_save', 'n_clicks'))  # If Tower Orientation Range Updated
def get_fig_system_orientation(_0, _1, _2):
    timestamp = time()
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
    # Get Tower Orientation
    tower = runner.indexing_table.position
    # Get Tower Limits
    auto_pilot_limits = runner.pilot.tower_limits
    # Compute blind zone to display
    if auto_pilot_limits[1] > auto_pilot_limits[0]:
        blind_zone_width = 360 - (auto_pilot_limits[1] - auto_pilot_limits[0])
    else:
        blind_zone_width = auto_pilot_limits[0] - auto_pilot_limits[1]
    blind_zone_center = auto_pilot_limits[1] + blind_zone_width / 2
    # Get ship heading
    ship = float('nan')
    if timestamp - runner.ship_heading_timestamp < runner.DATA_EXPIRED_DELAY:
        ship = runner.ship_heading
        # Adjust Tower to ship referencial
        tower = ship - runner.pilot.tower_zero + tower
        # Adjust blind zone to ship referencial
        blind_zone_center = ship + blind_zone_center
    # Get sun
    sun = float('nan')
    if timestamp - runner.sun_position_timestamp < runner.DATA_EXPIRED_DELAY and runner.sun_elevation > 0:
        sun = runner.sun_azimuth
    # Get HyperSAS Heading
    ths = float('nan')
    if timestamp - runner.hypersas.packet_THS_parsed < runner.DATA_EXPIRED_DELAY:
        if isnan(runner.gps.latitude):
            ths = runner.hypersas.compass
        else:
            ths = runner.hypersas.compass_adj
    # Get IMU Heading
    imu = float('nan')
    if runner.imu:
        if timestamp - runner.imu.packet_received < runner.DATA_EXPIRED_DELAY:
            if isnan(runner.gps.latitude):
                imu = runner.imu.yaw
            else:
                imu = get_true_north_heading(runner.imu.yaw,
                                             runner.gps.latitude, runner.gps.longitude,
                                             runner.gps.datetime, runner.gps.altitude)
    # Get motion heading from GPS
    motion = float('nan')
    if timestamp - runner.gps.packet_pvt_received < runner.DATA_EXPIRED_DELAY and \
            runner.gps.speed > 1:  # speed greater than 1 m/s -> 3.6 km/h
        motion = runner.gps.heading_motion
    # Patch figure with new data (partial update significantly reduce traffic)
    fig = Patch()
    if isnan(blind_zone_center) or isnan(blind_zone_width):
        fig['data'][blind_zone_id]['visible'] = False
    else:
        fig['data'][blind_zone_id]['visible'] = True
        fig['data'][blind_zone_id]['theta'] = [blind_zone_center]
        fig['data'][blind_zone_id]['width'] = [blind_zone_width]
    for id, value in ((ship_id, ship), (tower_id, tower), (sun_id, sun), (ths_id, ths), (imu_id, imu), (gps_motion_id, motion)):
        if isnan(value):
            fig['data'][id]['visible'] = False
        else:
            fig['data'][id]['visible'] = True
            fig['data'][id]['theta'] = [0, value]
    return fig


fig = go.Figure()
lt_id = 0
fig.add_scatter(x=[0, 1], y=[0, 1], name='Lt (&mu;W/cm<sup>2</sup>/nm/sr)', marker_color='#37536d', mode='lines',
                visible=False)
li_id = 1
fig.add_scatter(x=[0, 1], y=[0, 1], name='Li (&mu;W/cm<sup>2</sup>/nm/sr)', marker_color='#1a76ff', mode='lines',
                visible=False)
es_id = 2
fig.add_scatter(x=[0, 1], y=[0, 1], yaxis='y2', name='Es (&mu;W/cm<sup>2</sup>/nm)', marker_color='orange', mode='lines',
                visible=False)

fig.update_layout(
    title='HyperSAS Spectrum', title_x=0.5,
    showlegend=True, legend=dict(x=1.0, y=1.0, xanchor='right'),
    margin=dict(l=20, r=80, t=80, b=40),
    xaxis=dict(title=dict(text='Wavelength (nm)'), exponentformat='power', showgrid=True),
    yaxis=dict(title=dict(text='Radiance (&mu;W/cm<sup>2</sup>/nm/sr)'), showgrid=True, exponentformat='power'),
    yaxis2=dict(title=dict(text='Irradiance (&mu;W/cm<sup>2</sup>/nm)'),
                title_font_color='orange', tickfont_color='orange',
                side="right", anchor="x", overlaying="y")
)
fig_spectrum = fig


@app.callback(Output('fig_spectrum', 'figure'), Output('fig_spectrum_cache', 'data', allow_duplicate=True),
              Input('hypersas_reading_interval', 'n_intervals'),
              State('fig_spectrum_cache', 'data'), prevent_initial_call=True)
def get_fig_spectrum(_, cache):
    fig = Patch()
    if not cache:
        cache = [False] * 3
    # Check alive
    if not runner.hypersas.alive:
        cache = [False] * 3
        for id in range(3):
            fig['data'][id]['visible'] = False
    # Parse data
    timestamp = time()
    runner.hypersas.parse_packets()
    if runner.es:
        runner.es.parse_packets()
    # Update data
    if runner.hypersas.Lt is not None and timestamp - runner.hypersas.packet_Lt_parsed < runner.DATA_EXPIRED_DELAY:
        fig['data'][lt_id]['visible'] = True
        if cache[lt_id] is False:
            fig['data'][lt_id]['x'] = runner.hypersas.Lt_wavelength
            cache[lt_id] = True
        fig['data'][lt_id]['y'] = runner.hypersas.Lt
    else:
        fig['data'][lt_id]['visible'] = False
    if runner.hypersas.Li is not None and timestamp - runner.hypersas.packet_Li_parsed < runner.DATA_EXPIRED_DELAY:
        fig['data'][li_id]['visible'] = True
        if cache[li_id] is False:
            fig['data'][li_id]['x'] = runner.hypersas.Li_wavelength
            cache[li_id] = True
        fig['data'][li_id]['y'] = runner.hypersas.Li
    else:
        fig['data'][li_id]['visible'] = False
    if runner.es:
        if runner.es.Es is not None and timestamp - runner.es.packet_Es_parsed < runner.DATA_EXPIRED_DELAY:
            fig['data'][es_id]['visible'] = True
            if cache[es_id] is False:
                fig['data'][es_id]['x'] = runner.es.Es_wavelength
                cache[es_id] = True
            fig['data'][es_id]['y'] = runner.es.Es
        else:
            fig['data'][es_id]['visible'] = False
    else:
        if runner.hypersas.Es is not None and timestamp - runner.hypersas.packet_Es_parsed < runner.DATA_EXPIRED_DELAY:
            fig['data'][es_id]['visible'] = True
            if cache[es_id] is False:
                fig['data'][es_id]['x'] = runner.hypersas.Es_wavelength
                cache[es_id] = True
            fig['data'][es_id]['y'] = runner.hypersas.Es
        else:
            fig['data'][es_id]['visible'] = False
    return fig, cache


fig = go.Figure()
imu_pitch_id = 0
fig.add_scatter(x=[], y=[], name='Pitch (IMU)', marker_color='green', mode='lines+markers',
                visible=False)
imu_roll_id = 1
fig.add_scatter(x=[], y=[], name='Roll (IMU)', marker_color='green', line_dash='dash', mode='lines+markers',
                visible=False)
ths_pitch_id = 2
fig.add_scatter(x=[], y=[], name='Pitch (THS)', marker_color='gray', mode='lines+markers',
                visible=False)
ths_roll_id = 3
fig.add_scatter(x=[], y=[], name='Roll (THS)', marker_color='gray', line_dash='dash', mode='lines+markers',
                visible=False)
es_490_id = 4
fig.add_scatter(x=[], y=[], yaxis='y2', name='Es(490) (&mu;W/cm<sup>2</sup>/nm)',
                marker_color='orange', mode='lines+markers', visible=False)

fig.update_layout(
    showlegend=True, legend=dict(x=0, y=1.0),
    margin=dict(l=80, r=80, t=40, b=80),
    yaxis=dict(title=dict(text='Tilt | Roll (&deg;)'), showgrid=True, exponentformat='power',
               zeroline=True, zerolinecolor='black', zerolinewidth=2),
    yaxis2=dict(title=dict(text='Irradiance (&mu;W/cm<sup>2</sup>/nm)'),
                title_font_color='orange', tickfont_color='orange',
                side="right", anchor="x", overlaying="y")
)
fig_timeseries = fig


@app.callback(Output('fig_timeseries', 'figure'), Output('fig_timeseries_cache', 'data', allow_duplicate=True),
              Input('hypersas_reading_interval', 'n_intervals'),
              State('fig_timeseries_cache', 'data'), prevent_initial_call=True)
def get_fig_timeseries(_, cache):
    fig = Patch()
    timestamp = time()
    max_points = [120, 120, 60, 60, 90]
    if not cache:
        count, last_timestamp = [0] * 5, [0] * 5
        for id in range(5):
            fig['data'][id]['x'] = []
            fig['data'][id]['y'] = []
    else:
        count, last_timestamp = cache

    def set_patch(rx, dt, y, id):
        if timestamp - rx < runner.DATA_EXPIRED_DELAY and y is not None and not isnan(y):
            if last_timestamp[id] == dt:
                # Nothing to update
                return
            # Update timestamp to current point
            last_timestamp[id] = dt
            if count[id] < max_points[id]:
                count[id] += 1
            else:
                # Max number of points reached, remove oldest
                del fig['data'][id]['x'][0]
                del fig['data'][id]['y'][0]
            fig['data'][id]['x'].append(datetime.fromtimestamp(dt))
            fig['data'][id]['y'].append(y)
            fig['data'][id]['visible'] = True
        else:
            fig['data'][id]['visible'] = False

    # Get THS Heading
    set_patch(runner.hypersas.packet_THS_parsed, runner.hypersas._packet_THS_received,
              runner.hypersas.pitch, ths_pitch_id)
    set_patch(runner.hypersas.packet_THS_parsed, runner.hypersas._packet_THS_received,
              runner.hypersas.roll, ths_roll_id)
    # Get IMU Heading
    if runner.imu:
        set_patch(runner.imu.packet_received, runner.imu.packet_received,
                  runner.imu.pitch, imu_pitch_id)
        set_patch(runner.imu.packet_received, runner.imu.packet_received,
                  runner.imu.roll, imu_roll_id)
    # Get Es(490)
    if runner.es:
        if runner.es.Es is not None:
            wl_id = np.argmin(abs(np.array(runner.es.Es_wavelength) - 490))
            set_patch(runner.es.packet_Es_parsed, runner.es._packet_Es_received,
                      runner.es.Es[wl_id], es_490_id)
    else:
        if runner.hypersas.Es is not None:
            wl_id = np.argmin(abs(np.array(runner.hypersas.Es_wavelength) - 490))
            set_patch(runner.hypersas.packet_Es_parsed, runner.hypersas._packet_Es_received,
                      runner.hypersas.Es[wl_id], es_490_id)
    return fig, (count, last_timestamp)


content = html.Div([
    dbc.Row([
        dbc.Col([dcc.Graph(figure=fig_system_orientation, id='fig_system_orientation',
                           style={'height': '50vh'}, config=graph_config)],  md=4, sm=5, xs=12),
        dbc.Col([dcc.Graph(figure=fig_spectrum, id='fig_spectrum',
                           style={'height': '50vh'}, config=graph_config)], md=8, sm=7, xs=12),
        dcc.Store(id='fig_spectrum_cache'),
    ]),
    dbc.Row([
        dbc.Col([dcc.Graph(figure=fig_timeseries, id='fig_timeseries',
                           style={'height': '50vh'}, config=graph_config)], width=12),
        dcc.Store(id='fig_timeseries_cache'),
    ]),
], id="page-content")


###########
# Layout #
###########

app.layout = html.Div([
    sidebar, content,
    settings_modal, clock_sync_modal, halt_modal, error_modal,
    dcc.Interval(id='status_refresh_interval', interval=STATUS_REFRESH_INTERVAL),
    dcc.Interval(id='hypersas_reading_interval', interval=HYPERSAS_READING_INTERVAL),
    dbc.Button(id='load_content', class_name='d-none'),
    html.Div(id='no_output', className='d-none'),
    html.Div(id='no_output_client', className='d-none'),

])
