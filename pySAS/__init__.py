import logging
from logging.handlers import RotatingFileHandler, QueueHandler
from queue import Queue
# from io import StringIO
import os
import sys
import traceback
from geomag.geomag import GeoMag
import configparser

__version__ = '1.1.3'

# Setup logging
LOGGING_LEVEL = logging.INFO
logging.basicConfig(level=LOGGING_LEVEL)
root_logger = logging.getLogger()   # Get root logger


# Catch errors in log
def except_hook(exc_type, exc_value, exc_tb):
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    root_logger.error(tb)


sys.excepthook = except_hook

# Get path to configuration file
if len(sys.argv) == 2:
    CFG_FILENAME = sys.argv[1]
else:
    CFG_FILENAME = os.path.join(os.path.dirname(__file__), 'pysas_cfg.ini')

# Get path to engineering logs
cfg = configparser.ConfigParser()
if not cfg.read(CFG_FILENAME):
    root_logger.critical('Path to configuration file invalid')
    raise ValueError('Path to configuration file invalid')
path_to_log = cfg.get('Runner', 'path_to_logs', fallback=os.path.join(os.path.dirname(__file__), 'logs'))
if not os.path.isdir(path_to_log):
    os.mkdir(path_to_log)

# Logging to disk
log_filename = os.path.join(path_to_log, 'pySAS.log')
ch_file = RotatingFileHandler(log_filename, maxBytes=1048576 * 5, backupCount=9)
formater_file = logging.Formatter("%(asctime)s %(levelname)-7.7s [%(name)s]  %(message)s")
ch_file.setFormatter(formater_file)
root_logger.addHandler(ch_file)

# Add Logger Handler for User Interface
ui_log_queue = Queue(100)  # Use Queue
ch_ui = QueueHandler(ui_log_queue)
# ui_log_queue = StringIO()
# ch_ui = logging.StreamHandler(ui_log_queue)
formater_ui = logging.Formatter("%(asctime)s %(name)s: %(message)s\r\n")
ch_ui.setFormatter(formater_ui)
ch_ui.setLevel(logging.CRITICAL)
root_logger.addHandler(ch_ui)

# Set logging level of werkzeug as too verbose when starting production server
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# Load NOAA World Magnetic Model
WORLD_MAGNETIC_MODEL = GeoMag()

root_logger.info('pySAS v%s initialized' % __version__)

# Pretty print config
root_logger.info('Loaded configuration: %s' % CFG_FILENAME)
def pretty_print(d, indent=0):
    for key, value in d.items():
        if key.startswith('_'):
            continue
        if isinstance(value, dict) or isinstance(value, configparser.SectionProxy):
            root_logger.info('\t' * indent + str(key))
            pretty_print(value, indent+1)
        else:
            root_logger.info('\t' * indent + str(key) + ': ' + str(value))

pretty_print(cfg, 1)
