from pySatlantic.instrument import Instrument as pySat
from geomag.geomag import GeoMag
from datetime import datetime, timedelta
from struct import pack, unpack
import multiprocessing
from tqdm import tqdm
import configparser
import pandas as pd
import numpy as np
import warnings
import logging
import pytz
import glob
import os

from pysolar.solartime import leap_seconds_adjustments
from pysolar.solar import get_azimuth, get_altitude, get_solar_time
# pysolar_end_year = 2018  # v0.8
pysolar_end_year = 2020  # v0.9
for y in range(pysolar_end_year, datetime.now().year + 2):
    leap_seconds_adjustments.append((0, 0))


__version__ = '0.2.4'

# Load NOAA World Magnetic Model
WORLD_MAGNETIC_MODEL = GeoMag()


def wrap_to_360(angle):
    new_angle = angle
    while new_angle < 0:
        new_angle += 360
    while new_angle >= 360:
        new_angle -= 360
    return new_angle


class Converter:

    def __init__(self, path_to_cal, path_to_cfg):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.parser = pySat(path_to_cal)
        cfg = configparser.ConfigParser()
        try:
            if not cfg.read(path_to_cfg):
                self.logger.critical('Configuration file not found')
        except configparser.Error as e:
            self.logger.critical('Unable to parse configuration file')
        self.cfg_compass_zero = cfg.getfloat('AutoPilot', 'gps_orientation_on_ship', fallback=0)
        self.cfg_tower_zero = cfg.getfloat('AutoPilot', 'indexing_table_orientation_on_ship', fallback=0)
        self.cfg_target = cfg.getfloat('AutoPilot', 'optimal_angle_away_from_sun', fallback=135)

        # Protected variables to run in parallel run_dir
        self._gps_files, self._twr_files, self._sat_files = list(), list(), list()
        self._gps_solar, self._twr_solar, self._sat_solar = list(), list(), list()
        self._path_out, self._output_length = '', ''

    def read_sat(self, filename):
        d, ts = [], []
        ignored_bytes = 0
        n_frames = dict()
        # Read Raw Data (Frames.all)
        with open(filename, 'rb') as f:
            self.logger.info(f'Reading {filename}')
            buffer = f.read()
            frame = True

            pbar = tqdm(total=len(buffer), unit='bytes') if self.logger.getEffectiveLevel() <= logging.DEBUG else None
            while frame or unknown_bytes:
                if pbar:
                    pbar_buffer_len = len(buffer)
                # Get Frame
                frame, frame_header, buffer, unknown_bytes = self.parser.find_frame(buffer)
                if unknown_bytes:
                    if unknown_bytes[:6] == b'SATHDR' or unknown_bytes[:5] == b'BEGIN':
                        self.logger.debug('Skip SatView Header')
                    else:
                        self.logger.debug(unknown_bytes)
                        ignored_bytes += len(unknown_bytes)
                if frame:
                    if len(buffer) >= 7:
                        # Get SatView timestamp
                        timestamp = buffer[:7]
                        # Parse timestamp
                        timestamp = unpack('!ii', b'\x00' + timestamp)
                        try:
                            ts.append(datetime.strptime(str(timestamp[0]) + str(timestamp[1]).zfill(9) + '000', '%Y%j%H%M%S%f'))
                            # Shift buffer
                            buffer = buffer[7:]
                        except ValueError:
                            self.logger.error(f'{filename}: Time Impossible, frame likely corrupted.')
                            ts.append(float('nan'))
                    else:
                        # Missing data to read timestamp from SatView
                        # Refill buffer and go grab more data
                        buffer = frame + buffer
                        break
                    d.append(frame)
                    if frame_header not in n_frames.keys():
                        n_frames[frame_header] = 1
                    else:
                        n_frames[frame_header] += 1

                # Update progress bar
                if pbar:
                    pbar.update(pbar_buffer_len-len(buffer))
            if pbar:
                pbar.close()
        self.logger.info(f'Frames Found: {n_frames}')
        self.logger.info(f'Ignored Bytes: {ignored_bytes}')
        return pd.DataFrame({'timestamp': ts, 'frame': d})

    @staticmethod
    def make_gprmc(row):
        hhmmss = row.gps_datetime.strftime('%H%M%S')
        valid = 'A' if row.datetime_valid and row.fix_ok else 'V'
        lat_dd = np.floor(abs(row.latitude))
        lat_mm = (abs(row.latitude) - lat_dd) * 60
        lat_hm = 'S' if row.latitude < 0 else 'N'
        lon_ddd = np.floor(abs(row.longitude))
        lon_mm = (abs(row.longitude) - lon_ddd) * 60
        lon_hm = 'W' if row.longitude < 0 else 'E'
        speed = row.speed * 1.94384  # Convert from m/s to knots
        course = row.heading_motion
        ddmmyy = row.gps_datetime.strftime('%d%m%y')
        mag_var = WORLD_MAGNETIC_MODEL.GeoMag(row.latitude, row.longitude, row.altitude * 3.2808399, row.gps_datetime.date()).dec
        mag_var_hm = 'W' if mag_var < 0 else 'E'
        frame = f'$GPRMC,{hhmmss},{valid},{int(lat_dd):02d}{lat_mm:07.4f},{lat_hm},' \
                f'{int(lon_ddd):02d}{lon_mm:07.4f},{lon_hm},{speed:05.1f},{course:05.1f},' \
                f'{ddmmyy},{abs(mag_var):05.1f},{mag_var_hm}'
        checksum = 0
        for s in frame[1:]:
            checksum ^= ord(s)
        return bytes(f'{frame}*{hex(checksum)[2:]}\r\n', 'ascii')

    def make_umtwr(self, gps, tower):
        # Build sampling index
        # gps_idx = pd.DataFrame({'source': ['gps']*len(gps)}, index=gps.index)
        idx = pd.concat([pd.DataFrame({'datetime': gps.datetime, 'source': ['gps']*len(gps)}, index=gps.index),
                         pd.DataFrame({'datetime': tower.datetime, 'source': ['twr']*len(tower)}, index=tower.index)])
        idx = idx.sort_values(by='datetime')
        # Build frames
        d = list()
        ig, it = gps.index[0], tower.index[0]
        for k in range(len(idx)):
            if idx.source.iloc[k] == 'gps':
                ig = idx.index[k]
            else:  # idx.source.iloc[k] == 'twr'
                it = idx.index[k]
            heading_ship = wrap_to_360(gps.heading[ig] - self.cfg_compass_zero)
            heading_sas = wrap_to_360(heading_ship - self.cfg_tower_zero + tower.position[it])
            tower_status = 'S' if tower.stall_flag[it] else 'O'
            dt_utc = gps.gps_datetime[ig].replace(tzinfo=pytz.utc).to_pydatetime()
            sun_azimuth = get_azimuth(gps.latitude[ig], gps.longitude[ig], dt_utc, gps.altitude[ig])
            sun_elevation = get_altitude(gps.latitude[ig], gps.longitude[ig], dt_utc, gps.altitude[ig])
            frame = f'UMTWR,{heading_sas:03.2f},{heading_ship:06.2f},{gps.heading_accuracy[ig]:06.2f},' \
                    f'{gps.heading_motion[ig]:05.1f},{gps.heading_vehicle_accuracy[ig]:05.1f},' \
                    f'{tower.position[it]:06.2f},{tower_status},{sun_azimuth:05.1f},{sun_elevation:04.1f}\r\n'
            d.append(bytes(frame, 'ascii'))

        return pd.DataFrame({'timestamp': idx.datetime.to_numpy(), 'frame': d})

    def make_sathdr(self, values=dict()):
        keys = [b'CRUISE-ID', b'OPERATOR', b'INVESTIGATOR', b'AFFILIATION', b'CONTACT', b'EXPERIMENT',
                b'LATITUDE', b'LONGITUDE', b'ZONE', b'CLOUD_PERCENT', b'WAVE_HEIGHT', b'WIND_SPEED', b'COMMENT',
                b'DOCUMENT', b'STATION-ID', b'CAST', b'TIME-STAMP', b'MODE', b'TIMETAG', b'DATETAG', b'TIMETAG2',
                b'PROFILER', b'REFERENCE', b'PRO-DARK', b'REF-DARK']
        header = b''
        for k in keys:
            v = values[k] if k in values.keys() else b''
            sentence = b'SATHDR ' + v + b' (' + k + b')\r\n'
            if len(sentence) > 128:
                self.logger.warning(f'SATHDR {k} too long')
            sentence += b'\x00' * (128 - len(sentence))
            header += sentence
        return header

    def run(self, filename_sat, filename_gps, filename_tower, filename_output, output_length='all'):
        """

        :param filename_sat:
        :param filename_gps:
        :param filename_tower:
        :param filename_output:
        :param output_length: Length of output file options are 'all' or 'hour'
        :return:
        """
        # Read raw with system timestamp
        sat = list()
        for f in filename_sat if type(filename_sat) is list else [filename_sat]:
            sat.append(self.read_sat(f))
        if not sat:
            self.logger.warning('No valid Satlantic file')
            return
        sat = pd.concat(sat, ignore_index=True).dropna()

        # Read GPS and Tower
        self.logger.debug('Reading GPS and Tower files')
        gps = list()
        for f in filename_gps if type(filename_gps) is list else [filename_gps]:
            try:
                gps.append(pd.read_csv(f, skiprows=[1], skipinitialspace=True, na_values=['None'],
                                       parse_dates=[0,1], infer_datetime_format=True))
            except pd.errors.EmptyDataError:
                self.logger.warning(f'Empty GPS file {f}')
            except ValueError:
                self.logger.warning(f'Invalid GPS file {f}')
        if not gps:
            self.logger.warning('No valid GPS file')
            return
        gps = pd.concat(gps, ignore_index=True).dropna(how='all').dropna(subset=['datetime', 'gps_datetime'])
        twr = list()
        for f in filename_tower if type(filename_tower) is list else [filename_tower]:
            try:
                twr.append(pd.read_csv(f, skiprows=[1], skipinitialspace=True, na_values=['None'],
                                       parse_dates=[0], infer_datetime_format=True))
            except pd.errors.EmptyDataError:
                self.logger.warning(f'Empty indexing table file {f}')
                continue
            except ValueError:
                self.logger.warning(f'Invalid indexing table file {f}')
        if not twr:
            self.logger.warning('No valid indexing table file')
            return
        twr = pd.concat(twr, ignore_index=True).dropna(how='all').dropna(subset=['datetime'])
        stall_flag = twr.stall_flag[0]
        for k in twr.index:
            if np.isnan(twr.stall_flag[k]):
                twr.loc[k, 'stall_flag'] = stall_flag
            else:
                stall_flag = twr.stall_flag[k]
        twr.loc[pd.isna(twr.stall_flag), 'stall_flag'] = False
        twr = twr.loc[(~np.isnan(twr.position)), :]

        # Make new frames
        self.logger.info('Converting GPS and Tower frames to Satlantic format')
        gprmc = pd.DataFrame({'timestamp': gps.datetime.to_numpy(), 'frame': gps.apply(self.make_gprmc, axis='columns').to_numpy()})
        umtwr = self.make_umtwr(gps, twr)

        # Interpolate frames
        all = pd.concat([sat, gprmc, umtwr]).sort_values(by=['timestamp'], ignore_index=True)

        # Make SATHDR
        hdr = self.make_sathdr({b'LATITUDE': bytes(f'{gps.latitude.min()}:{gps.latitude.max()}', 'ascii'),
                                b'LONGITUDE': bytes(f'{gps.longitude.min()}:{gps.longitude.max()}', 'ascii'),
                                b'ZONE': b'UTC',
                                b'COMMENT': bytes(f'gps_orientation_on_ship={self.cfg_compass_zero};'
                                                  f'indexing_table_orientation_on_ship={self.cfg_tower_zero};'
                                                  f'optimal_angle_away_from_sun={self.cfg_target};', 'ascii'),
                                b'TIME-STAMP': bytes(sat.timestamp.min().strftime('%a %b %d %H:%M:%S %Y'), 'ascii')})

        # Write to file
        if output_length == 'all':
            all_sel = [[True] * len(all)]
            filenames = [filename_output]
        elif output_length == 'hour':
            all_sel, filenames = list(), list()
            path, ext = os.path.splitext(filename_output)
            ts = all.timestamp[0]
            while ts < all.timestamp.max():
                sel = (ts <= all.timestamp) & (all.timestamp < ts + timedelta(hours=1))
                if any(sel):
                    all_sel.append(sel)
                    filenames.append(f"{path}_{ts.strftime('%H%M%S')}{ext}")
                ts += timedelta(hours=1)
        for filename, sel in zip(filenames, all_sel):
            self.logger.info(f'Writing {filename}')
            with open(filename, mode='wb') as f:
                f.write(hdr)
                for k in all.index[sel]:
                    f.write(all.frame[k])
                    timestamp = pack('!ii', int(all.timestamp[k].strftime('%Y%j')),
                                            int(all.timestamp[k].strftime('%H%M%S%f')[:-3]))[1:]
                    f.write(timestamp)

    def run_dir(self, path_in, path_out, file_out_prefix='pySAS_', mode='day', parallel=True):
        """
        Convert pySAS output located in one directory to Satlantic files.
        Can either process all files at once (mode='all') or files day by day (mode='day').

        Does not handle files overlapping on two days (passing midnight solar time)
        :param path_in: path to directory containing pySAS output (gps, indexing table, and satlantic files).
        :param path_out: path to directory (if mode='day'|'hour') or file (if mode='all') to write assembled data file (.raw).
        :param mode: process all files of directory at once ('all') or process data files by day ('day') or by hour ('hour'). Use mean solar time (MSR) as time zone.
        :param parallel: if mode is day or hour then process days present in directory in parallel (default: True).
        return: None
        """

        # List all files and get timestamp
        self._gps_files = sorted(glob.glob(os.path.join(path_in, 'GPS_*.csv')))
        self._twr_files = sorted(glob.glob(os.path.join(path_in, 'IndexingTable_*.csv')))
        self._sat_files = sorted(glob.glob(os.path.join(path_in, 'HyperSAS_*.bin')))

        # Process all files in directory at once
        if mode == 'all':
            self.run(self._sat_files, self._gps_files, self._twr_files,
                     f'{path_out[:-1] if path_out.endswith(os.sep) else path_out}.raw')
            return

        # Read all longitude available in directory
        pos = list()
        for f in self._gps_files:
            try:
                pos.append(pd.read_csv(f, skiprows=[1], skipinitialspace=True, usecols=['datetime', 'longitude'],
                                       parse_dates=[0, 1], infer_datetime_format=True))
            except pd.errors.EmptyDataError:
                self.logger.warning(f'Empty GPS file {f}')
            except ValueError:
                self.logger.warning(f'Invalid GPS file {f}')
        if not pos:
            self.logger.warning('No valid GPS file')
            return
        pos = pd.concat(pos, ignore_index=True)
        pos = pos.loc[~pd.isnull(pos.datetime)]
        pos['timestamp'] = pos.datetime.apply(lambda row: row.timestamp()).to_numpy()

        # Get date and time of each file (UTC)
        gps_dt = np.array([datetime.strptime(os.path.basename(f) + '+0000', 'GPS_%Y%m%d_%H%M%S.csv%z') for f in self._gps_files])
        twr_dt = np.array([datetime.strptime(os.path.basename(f) + '+0000', 'IndexingTable_%Y%m%d_%H%M%S.csv%z') for f in self._twr_files])
        sat_dt = np.array([datetime.strptime(os.path.basename(f) + '+0000', 'HyperSAS_%Y%m%d_%H%M%S.bin%z') for f in self._sat_files])

        # Compute solar time of each file
        # NOTE: Longitude must be between -180 and +180 (it's the case with the ardusimple gps output used in pySAS)
        warnings.filterwarnings('ignore', category=DeprecationWarning)  # Warning issued by pysolar library using numpy
        vts = np.vectorize(datetime.timestamp)
        gps_solar = get_solar_time(np.interp(vts(gps_dt), pos.timestamp, pos.longitude.to_numpy(dtype=np.float)), gps_dt)  # Only hour
        self._gps_solar = np.array([d.date() + timedelta(hours=t) for d, t in zip(gps_dt, gps_solar)])                     # Complete date time
        twr_solar = get_solar_time(np.interp(vts(twr_dt), pos.timestamp, pos.longitude.to_numpy(dtype=np.float)), twr_dt)
        self._twr_solar = np.array([d.date() + timedelta(hours=t) for d, t in zip(twr_dt, twr_solar)])
        sat_solar = get_solar_time(np.interp(vts(sat_dt), pos.timestamp, pos.longitude.to_numpy(dtype=np.float)), sat_dt)
        self._sat_solar = np.array([d.date() + timedelta(hours=t) for d, t in zip(sat_dt, sat_solar)])
        warnings.simplefilter('default', category=DeprecationWarning)

        # Process all files of a single day
        self._path_out = os.path.join(path_out, file_out_prefix)
        self._output_length = 'hour' if mode == 'hour' else 'all'
        if parallel:
            with multiprocessing.Pool() as pool:
                pool.map(self._run_day, np.unique(self._sat_solar).tolist())
        else:
            for d in np.unique(self._sat_solar):
                self._run_day(d)

    def _run_day(self, d):
        gps_sel = self._gps_solar == d
        if not np.any(gps_sel):
            self.logger.warning(f'No GPS file on {d}')
            return
        twr_sel = self._twr_solar == d
        if not np.any(twr_sel):
            self.logger.warning(f'No IndexingTable file on {d}')
            return
        sat_sel = self._sat_solar == d
        self.logger.debug(f'Converting day {d}')
        self.run([f for f, sel in zip(self._sat_files, sat_sel) if sel],
                 [f for f, sel in zip(self._gps_files, gps_sel) if sel],
                 [f for f, sel in zip(self._twr_files, twr_sel) if sel],
                 f'{self._path_out}{d.strftime("%Y%m%d")}.raw',
                 output_length=self._output_length)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Convert output from the University of Maine pySAS tower system to ")

    parser.add_argument('-v', '--version', action='version', version=f'{__file__} v{__version__}')
    parser.add_argument('--cal', nargs='?', required=True, help="HyperSAS & Es calibration files (.sip)")
    parser.add_argument('--cfg', nargs='?', required=True, help="pySAS configuration file (.ini).")
    parser.add_argument('-s', '--sat', nargs='?', help="path to HyperSAS & Es (.bin) file to process")
    parser.add_argument('-g', '--gps', nargs='?', help="path to GPS file needed to process HyperSAS file")
    parser.add_argument('-t', '--tower', nargs='?', help="path to Indexing Table file needed to process HyperSAS file")
    parser.add_argument('-d', '--directory', nargs='?', help="path to directory of files to process")
    parser.add_argument('-m', '--mode', choices=['all', 'day'], help="process all files in directory (all) or process files day by day (default: day), only applicable when converting from directory")
    parser.add_argument('-f', '--file_out_prefix', nargs='?', help="prefix of output file when process directory")
    parser.add_argument('-e', '--experiment', nargs='?', help="SeaBASS name of experiment")
    parser.add_argument('-c', '--cruise', nargs='?', help="SeaBASS name of cruise")
    parser.add_argument('out', help="path to directory or filename of converted data.")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    logging.debug(args)

    c = Converter(args.cal, args.cfg)
    if args.directory:
        file_out_prefix = args.experiment if args.experiment is not None else ''
        file_out_prefix += '_' + args.cruise if args.cruise is not None else ''
        args.file_out_prefix = file_out_prefix + '_' if file_out_prefix else args.file_out_prefix
        kwargs = {'file_out_prefix': args.file_out_prefix} if args.file_out_prefix is not None else {}
        c.run_dir(args.directory, args.out, mode=args.mode, **kwargs)
    elif args.sat and args.gps and args.tower:
        c.run(args.sat, args.gps, args.tower, args.out)
    else:
        print(f"{__name__}: error: the following arguments are required: (--sat, --gps, and --tower) or (--directory)")
