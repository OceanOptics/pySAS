import logging
from logging.handlers import RotatingFileHandler  #, QueueHandler
from time import strftime, gmtime
# from queue import Queue
from io import StringIO
import os
from geomag.geomag import GeoMag

__version__ = '0.3.1'

# Global Variables
CFG_FILENAME = os.path.join(os.path.dirname(__file__), 'pysas_cfg.ini')
LOGGING_LEVEL = logging.DEBUG

# Setup application logging
if not os.path.isdir('logs'):
    os.mkdir('logs')

# Setup logging
logging.basicConfig(level=LOGGING_LEVEL)
root_logger = logging.getLogger()   # Get root logger

# Logging in file
path_to_log = os.path.join(os.path.dirname(__file__), 'logs')
if not os.path.isdir(path_to_log):
    os.mkdir(path_to_log)
log_filename = os.path.join(path_to_log, 'pySAS_' + strftime('%Y%m%d_%H%M%S', gmtime()) + '.log')
ch_file = RotatingFileHandler(log_filename, maxBytes=1048576 * 5, backupCount=9)
formater_file = logging.Formatter("%(asctime)s %(levelname)-7.7s [%(name)s]  %(message)s")
ch_file.setFormatter(formater_file)
root_logger.addHandler(ch_file)

# Add Logger Handler for User Interface
# ui_log_queue = Queue(100)  # Use Queue
ui_log_queue = StringIO()
ch_ui = logging.StreamHandler(ui_log_queue)
formater_ui = logging.Formatter("%(asctime)s %(name)s: %(message)s\r\n")
ch_ui.setFormatter(formater_ui)
ch_ui.setLevel(logging.CRITICAL)
root_logger.addHandler(ch_ui)

# Set logging level of werkzeug as too verbose when starting production server
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# root_logger.debug('__init__')

# Load NOAA World Magnetic Model
WORLD_MAGNETIC_MODEL = GeoMag()
