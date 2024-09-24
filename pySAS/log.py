import os
from math import isnan
from queue import Queue, Empty
from threading import Thread
from time import gmtime, strftime, time
from struct import pack
import atexit
from typing import Union, IO


class Log:

    FILE_EXT = 'csv'
    FILE_MODE = 'w'

    def __init__(self, cfg):
        # Load Config
        if 'filename_prefix' not in cfg.keys():
            cfg['filename_prefix'] = 'Inlinino'
        if 'path' not in cfg.keys():
            cfg['path'] = ''
        if 'length' not in cfg.keys():
            cfg['length'] = 60  # minutes
        if 'variable_names' not in cfg.keys():
            cfg['variable_names'] = []
        if 'variable_units' not in cfg.keys():
            cfg['variable_units'] = []
        if 'variable_precision' not in cfg.keys():
            cfg['variable_precision'] = []

        self._file = None
        self._file_timestamp = None
        # self.file_mode_binary = cfg['mode_binary']
        self.file_length = cfg['length'] * 60 # seconds
        self.filename_prefix = cfg['filename_prefix']
        self.path = cfg['path']

        self.variable_names = cfg['variable_names']
        self.variable_units = cfg['variable_units']
        self.variable_precision = cfg['variable_precision']

        self.terminator = '\r\n'

    def open(self, timestamp):
        # Create directory
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        # Generate unique filename
        filename = os.path.join(self.path, self.filename_prefix + '_' +
                                strftime('%Y%m%d_%H%M%S', gmtime(timestamp)) + '.' + self.FILE_EXT)
        suffix = 0
        while os.path.exists(filename):
            filename = os.path.join(self.path, self.filename_prefix + '_' +
                                    strftime('%Y%m%d_%H%M%S', gmtime(timestamp)) + '_' + str(suffix) + '.' + self.FILE_EXT)
            suffix += 1
        # Create File
        self._file = open(filename, self.FILE_MODE)
        # Write header (only if has variable names)
        if self.variable_names:
            self._file.write(
                'datetime, ' + ', '.join(x for x in self.variable_names) + self.terminator)
            self._file.write(
                'yyyy/mm/dd HH:MM:SS.fff, ' + ', '.join(x for x in self.variable_units) + self.terminator)
        # Time file open
        self._file_timestamp = timestamp

    def _smart_open(self, timestamp):
        # Open file if necessary
        if self._file is None or self._file.closed or \
                gmtime(self._file_timestamp).tm_mday != gmtime(timestamp).tm_mday or \
                timestamp - self._file_timestamp >= self.file_length:
            # Close previous file if open
            if self._file and not self._file.closed:
                self.close()
            # Create new file
            self.open(timestamp)

    def write(self, data, timestamp):
        """
        Write data to file
        :param data: list of values
        :param timestamp: date and time associated with the data frame
        :return:
        """
        self._smart_open(timestamp)
        if self.variable_precision:
            self._file.write(strftime('%Y/%m/%d %H:%M:%S', gmtime(timestamp)) + ("%.3f" % timestamp)[-4:] +
                             ', ' + ', '.join(p % d for p, d in zip(self.variable_precision, data)) + self.terminator)
        else:
            self._file.write(strftime('%Y/%m/%d %H:%M:%S', gmtime(timestamp)) + ("%.3f" % timestamp)[-4:] +
                             ', ' + ', '.join(str(d) for d in data) + self.terminator)

    def close(self):
        if self._file:
            self._file.close()
        self._file_timestamp = None

    def __del__(self):
        self.close()


class LogBinary(Log):

    FILE_EXT = 'bin'
    FILE_MODE = 'wb'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.variable_names = []
        self.variable_units = []
        self.timestamp_packer = pack_timestamp

    def write(self, data, timestamp):
        self._smart_open(timestamp)
        self._file.write(data + self.timestamp_packer(timestamp))


def pack_timestamp(timestamp):
    return pack('!d', timestamp)


def pack_timestamp_satlantic(timestamp):
    s, ms = divmod(timestamp, 1)
    return pack('!ii', int(strftime('%Y%j', gmtime(s))),
                int('{}{:03d}'.format(strftime('%H%M%S', gmtime(s)), int(ms * 1000))))[1:]


class LogText(Log):

    FILE_EXT = 'raw'
    ENCODING = 'utf-8'
    UNICODE_HANDLING = 'replace'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.variable_names = ['packet']
        self.variable_units = [self.ENCODING]
        self.registration = ''

    def write(self, data, timestamp):
        """
        Write raw ascii data to file
        :param data: typically a binary array of ascii characters
        :param timestamp: date and time associated with the data frame
        :return:
        """
        self._smart_open(timestamp)
        self._file.write(strftime('%Y/%m/%d %H:%M:%S', gmtime(timestamp)) + ("%.3f" % timestamp)[-4:] +
                         ', ' + self.registration + data.decode(self.ENCODING, self.UNICODE_HANDLING) + self.terminator)


class SatlanticLogger:
    """
    Thread Safe Satlantic Data logger. It writes data to file in Satlantic format.
    Rotates files automatically based on timestamp. The write method is thread safe.
    """
    def __init__(self, cfg):
        # Load configuration
        self.file_length: int = cfg['length'] * 60 if 'length' in cfg.keys() else 60 * 60 # seconds
        self.filename_prefix: str = cfg['filename_prefix'] if 'filename_prefix' in cfg.keys() else os.uname()[1].replace('pysas', 'pySAS')
        self.filename_ext: str = cfg['filename_ext'] if 'filename_ext' in cfg.keys() else 'raw'
        self.path: str = cfg['path'] if 'path' in cfg.keys() else ''

        # File Handler
        self._file: IO = None
        self._file_timestamp: Union[int, None] = None  # time.time

        # Thread Safe Queue
        self._queue: Queue = Queue()
        self._thread: Thread = None
        self._alive: bool = False

        # Safe exit
        atexit.register(self.close)

    def _start_thread(self):
        """
        Start writing thread

        :return:
        """
        if not self._alive:
            self._alive = True
            self._thread = Thread(name=repr(self), target=self._run)
            self._thread.daemon = True
            self._thread.start()

    def _stop_thread(self):
        """
        Stop writing thread

        :return:
        """
        if self._alive:
            self._alive = False

    def join(self, timeout=None):
        """
        Wait for thread writing data to join

        :param timeout:
        :return:
        """
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self):
        """
        Write to file data queued in thread
        :return:
        """
        while self._alive:
            item = None
            try:
                data, timestamp = self._queue.get(timeout=1)
            except Empty:
                # Use timeout to exit thread in timely fashion when stop thread
                continue
            self._smart_open(timestamp)
            self._file.write(data + pack_timestamp_satlantic(timestamp))

    def _smart_open(self, timestamp: int):
        """
        Open file if not opened or time to roll to new file

        :param timestamp: timestamp of data to write in file
        :return:
        """
        # Open file if necessary
        if self._file is None or self._file.closed or \
                gmtime(self._file_timestamp).tm_mday != gmtime(timestamp).tm_mday or \
                timestamp - self._file_timestamp >= self.file_length:
            # Close previous file if open
            if self._file and not self._file.closed:
                self.close()
            # Create new file
            self.open(timestamp)

    def open(self, timestamp: int):
        """
        Open file in which data is written

        :param timestamp: timestamp used in filename
        :return:
        """
        # Create directory
        if not os.path.exists(self.path):
            os.makedirs(self.path)
        # Generate unique filename
        filename = os.path.join(self.path, self.filename_prefix + '_' +
                                strftime('%Y%m%d_%H%M%S', gmtime(timestamp)) + '.' + self.filename_ext)
        suffix = 0
        while os.path.exists(filename):
            filename = os.path.join(self.path, self.filename_prefix + '_' +
                                    strftime('%Y%m%d_%H%M%S', gmtime(timestamp)) + '_' + str(suffix) + '.' + self.filename_ext)
            suffix += 1
        # Create File
        self._file = open(filename, 'wb')
        # Time file open
        self._file_timestamp = timestamp

    def write(self, data: bytes, timestamp: int = None):
        """
        Queue data to write to file (thread safe)

        :param data: data to write file (must be bytes)
        :param timestamp: timestamp of data
        :return:
        """
        if timestamp is None or isnan(timestamp):
            timestamp = time()
        self._queue.put((data, timestamp))
        if not self._alive:
            self._start_thread()

    def close(self):
        """
        Close opened file, can be used to reset filename

        :return:
        """
        if self._file:
            self._file.close()
        self._file_timestamp = None
