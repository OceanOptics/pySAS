import re
import os
import glob
import logging
import configparser
import multiprocessing
from functools import reduce
from operator import xor
from time import time
from datetime import datetime, timedelta, timezone
from struct import pack, unpack
from struct import error as StructError

import numpy as np
import pandas as pd
from tqdm import tqdm
from geomag.geomag import GeoMag
from pySatlantic.instrument import Instrument as pySat
from pysolar.solartime import leap_seconds_adjustments
from pysolar.solar import get_azimuth, get_altitude

# pysolar_end_year = 2018  # v0.8
from tqdm.contrib.logging import logging_redirect_tqdm

pysolar_end_year = 2020  # v0.9
for y in range(pysolar_end_year, datetime.now().year + 2):
    leap_seconds_adjustments.append((0, 0))

__version__ = '1.0.0'
logger = logging.getLogger('prepSAS')

# Load NOAA World Magnetic Model
WORLD_MAGNETIC_MODEL = GeoMag()


class Converter:

    def __init__(self, path_to_cal, path_to_cfg):
        self.parser = pySat(path_to_cal)
        cfg = configparser.ConfigParser()
        try:
            if not cfg.read(path_to_cfg):
                logger.critical('Configuration file not found')
        except configparser.Error as e:
            logger.critical('Unable to parse configuration file')
        self.cfg_compass_zero = cfg.getfloat('AutoPilot', 'gps_orientation_on_ship', fallback=0)
        self.cfg_tower_zero = cfg.getfloat('AutoPilot', 'indexing_table_orientation_on_ship', fallback=0)
        self.cfg_target = cfg.getfloat('AutoPilot', 'optimal_angle_away_from_sun', fallback=135)

        # Protected variables to run in parallel run_dir
        self._gps_files, self._twr_files, self._sat_files = list(), list(), list()
        self._gps_solar, self._twr_solar, self._sat_solar = list(), list(), list()
        self._path_out, self._output_length = '', ''

    def read_sat(self, filenames):
        """
        Read Satlantic file(s), much faster than method provided in pySatlantic format
        Split raw data based on frame header instead of using pySatlantic.instrument.Instrument.find_frame method
        :param filenames: list of file names to read
        :param headers:
        :return:
        """
        data = list()
        with logging_redirect_tqdm():
            for filename in tqdm(filenames if isinstance(filenames, list) else [filenames], 'Reading SAT'):
                # tic = time()
                with open(filename, 'rb') as f:
                    # logger.debug(f'Reading {filename}')
                    raw = f.read()
                if len(raw) == 0:
                    logger.warning(f'{os.path.basename(filename)}:Empty file.')
                    continue
                # logger.debug(f'read in {time()-tic:.3f} s')
                # Separate frames (too slow when multiple frame headers)
                # tic = time()
                # frames = [raw]
                # for header in parsed_headers:
                #     tmp = []
                #     for d in frames:
                #         data = d.split(header)
                #         tmp = tmp + [header + data[0] if d.startswith(header) else data[0]] + [header + x for x in data[1:]]
                #     frames = tmp
                # logger.debug(f'split in {time() - tic:.3f} s')
                # Parse Headers
                # tic = time()
                # headers = []
                # n_frames = {}
                # for frame in frames:
                #     for header in parsed_headers:
                #         if frame.startswith(header):
                #             headers.append(header)
                #             break
                #     else:
                #         # logger.debug(f'HeaderError: {frame}')
                #         headers.append(None)
                # logger.debug(f'headers in {time() - tic:.3f} s')
                # Separate frames with regex
                # tic = time()
                frames = re.split(b'(' +  b'|'.join([re.escape(k.encode('ASCII'))
                                                     for k in self.parser.cal.keys()]) + b')', raw)
                if len(frames[0]):
                    logger.warning(f'{os.path.basename(filename)}:ignored first bytes: {frames[0][:1000]}')  # Only display first thousand bytes
                if len(frames) < 2:
                    logger.warning(f'{os.path.basename(filename)}:No frames found.')
                    continue
                headers = frames[1::2]
                frames = [h + d for h, d in zip(headers, frames[2::2])]
                # logger.debug(f'split in {time() - tic:.3f} s')
                # Remove header frames
                # tic = time()
                for i, frame in enumerate(frames):
                    if frame.startswith(b'SATHDR'):
                        del frames[i]
                        del headers[i]
                # logger.debug(f'sathdr in {time() - tic:.3f} s')
                # Parse Time
                # tic = time()
                d, t = np.empty(len(frames), dtype=int), np.empty(len(frames), dtype=int)
                for i, frame in enumerate(frames):
                    try:
                        d[i], t[i] = unpack('!ii', b'\x00' + frame[-7:])
                        frames[i] = frame[:-7]  # Remove timestamp from frame
                    except (StructError):
                        # logger.debug(f'TimeError: {frame}')
                        d[i], t[i] = 0, 0
                df = pd.DataFrame({'d': d, 't': t})
                df['dt'] = df.d.astype(str) + df.t.astype(str).apply(lambda y: y.zfill(9)) + '000'
                timestamps = pd.to_datetime(df['dt'], format='%Y%j%H%M%S%f', utc=True, errors='coerce')
                timestamps[(timestamps < datetime(2020, 1, 1, tzinfo=timezone.utc)) |
                           (datetime.utcnow().astimezone(timezone.utc) < timestamps)] = pd.NaT
                # logger.debug(f'timestamp in {time() - tic:.3f} s')
                data.append(pd.DataFrame({'timestamp': timestamps, 'header': headers, 'frame': frames}))
        if not data:
            logger.warning('No valid Satlantic data.')
            return
        return pd.concat(data, ignore_index=True).dropna()

    @staticmethod
    def read_gps(filename):
        """
        Read pySAS GPS file(s)
        :param filename: list of filename(s) to read
        :return:
        """
        data = list()
        with logging_redirect_tqdm():
            for f in tqdm(filename if isinstance(filename, list) else [filename], 'Reading GPS'):
                # logger.info(f'Reading {f}')
                try:
                    data.append(pd.read_csv(f, skiprows=[1], skipinitialspace=True, na_values=['None'],
                                            parse_dates=[0, 1], infer_datetime_format=True))
                except pd.errors.EmptyDataError:
                    logger.warning(f'Empty GPS file {f}')
                except ValueError:
                    logger.warning(f'Invalid GPS file {f}')
        if not data:
            logger.warning('No valid GPS data.')
            return
        data = pd.concat(data, ignore_index=True)\
            .dropna(how='all').dropna(subset=['datetime', 'gps_datetime'])\
            .reset_index(drop=True)
        data.datetime = data.datetime.dt.tz_localize('UTC')
        data.gps_datetime = data.gps_datetime.dt.tz_localize('UTC')
        data.datetime_valid = data.datetime_valid.astype(bool)
        data.heading_valid = data.heading_valid.astype(bool)
        data.heading_vehicle_valid = data.heading_vehicle_valid.astype(bool)
        data.fix_ok = data.fix_ok.astype(bool)
        return data

    @staticmethod
    def read_twr(filename):
        """
        Read pySAS Tower/Indexing Table file(s)
        :param filename: list of filename(s) to read
        :return:
        """
        data = list()
        with logging_redirect_tqdm():
            for f in tqdm(filename if type(filename) is list else [filename], 'Reading TWR'):
                # logger.debug(f'Reading {f}')
                try:
                    data.append(pd.read_csv(f, skiprows=[1], skipinitialspace=True, na_values=['None'],
                                            parse_dates=[0], infer_datetime_format=True))
                except pd.errors.EmptyDataError:
                    logger.warning(f'Empty indexing table file {f}')
                    continue
                except ValueError:
                    logger.warning(f'Invalid indexing table file {f}')
        if not data:
            logger.warning('No valid indexing table file')
            return
        data = pd.concat(data, ignore_index=True).dropna(how='all').dropna(subset=['datetime'])
        # Propagate stall flag and drop empty lines
        data.stall_flag = data.stall_flag.fillna(method='ffill', limit=20)
        data.stall_flag = data.stall_flag.fillna(method='bfill', limit=3)
        data = data.dropna(subset=['position', 'stall_flag']).reset_index(drop=True)
        data.stall_flag = data.stall_flag.astype(bool)
        data.datetime = data.datetime.dt.tz_localize('UTC')
        return data

    @staticmethod
    def make_gprmc(df, compute_magnetic_declination=True):
        """
        Make $GPRMC NMEA frames to be ingested by HyperInSPACE
        :param df: gps data frame
        :param compute_magnetic_declination: Enable computation of magnetic declination (very slow)
        :return:
        """
        logger.debug('Making $GPRMC frames ...')
        hhmmss = df.gps_datetime.dt.strftime('%H%M%S')
        valid = pd.Series(['V'] * len(df))
        valid[df.datetime_valid & df.fix_ok] = 'A'
        lat_dd = np.floor(np.abs(df.latitude))
        lat_mm = ((np.abs(df.latitude) - lat_dd) * 60).apply(lambda x: f'{x:07.4f}')
        lat_dd = lat_dd.apply(lambda x: f'{x:02.0f}')
        lat_hm = pd.Series(['N'] * len(df))
        lat_hm[df.latitude < 0] = 'S'
        lon_ddd = np.floor(np.abs(df.longitude))
        lon_mm = ((np.abs(df.longitude) - lon_ddd) * 60).apply(lambda x: f'{x:07.4f}')
        lon_ddd = lon_ddd.apply(lambda x: f'{x:03.0f}')
        lon_hm = pd.Series(['E'] * len(df))
        lon_hm[df.longitude < 0] = 'W'
        speed = (df.speed * 1.94384).apply(lambda x: f'{x:05.1f}')  # Convert from m/s to knots
        course = (df.heading_motion).apply(lambda x: f'{x:05.1f}')
        ddmmyy = df.gps_datetime.dt.strftime('%d%m%y')
        if compute_magnetic_declination:
            # vgeomag = np.vectorize(WORLD_MAGNETIC_MODEL.GeoMag)
            # vgeomag(df.latitude, df.longitude, df.altitude * 3.2808399, df.gps_datetime.dt.date)
            mag_var = df.apply(lambda row: WORLD_MAGNETIC_MODEL.GeoMag(
                row.latitude, row.longitude, row.altitude * 3.2808399, row.gps_datetime.date()).dec, axis='columns')
            mag_var_hm = pd.Series(['E'] * len(df))
            mag_var_hm[mag_var < 0] = 'W'
            mag_var = np.abs(mag_var).apply(lambda x: f'{x:05.1f}')
        else:
            row = df.loc[0]
            mag_var = WORLD_MAGNETIC_MODEL.GeoMag(row.latitude, row.longitude,
                                                  row.altitude * 3.2808399, row.gps_datetime.date()).dec
            mag_var_hm = pd.Series(['W' if mag_var < 0 else 'E'] * len(df))
            mag_var = pd.Series([f'{abs(mag_var):05.1f}'] * len(df))
        frame = pd.Series(['$GPRMC'] * len(df)) + ',' + hhmmss + ',' + valid + ',' + \
                lat_dd + lat_mm + ',' + lat_hm + ',' + lon_ddd + lon_mm + ',' + lon_hm + ',' + \
                speed + ',' + course + ',' + ddmmyy + ',' + mag_var + ',' + mag_var_hm
        checksum = frame.apply(lambda frame: f'*{hex(reduce(xor, map(ord, frame[1:])))[2:]}\r\n')
        return pd.DataFrame({'timestamp': df.datetime.to_numpy(),
                             'frame': (frame + checksum).str.encode('ascii')})

    def make_umtwr(self, gps, tower, parallel=True, sun_pos_rule='30S'):
        """
        Make University of Maine Tower/Indexing Table frames

        :param gps: gps data frame
        :param tower: tower data frame
        :param parallel: use all cores available to compute sun position
        :param sun_pos_rule: increase speed
        :return:
        """
        logger.debug('Making UMTWR frames ...')
        # Build sampling index
        idx = pd.concat([pd.DataFrame({'datetime': gps.datetime, 'source': ['gps'] * len(gps), 'ig': gps.index}),
                         pd.DataFrame({'datetime': tower.datetime, 'source': ['twr'] * len(tower), 'it': tower.index})],
                        ignore_index=True)
        idx = idx.sort_values(by='datetime')
        idx.ig = idx.ig.fillna(method='ffill', limit=15)
        idx.it = idx.it.fillna(method='ffill')
        idx.dropna(inplace=True)
        idx.ig = idx.ig.astype(int, copy=False)
        idx.it = idx.it.astype(int, copy=False)
        # Compute sun elevation
        global sun_position

        def sun_position(args):
            # args = lat, lon, dt_utc, altitude
            return f'{get_azimuth(*args):05.1f}', f'{get_altitude(*args):04.1f}'

        # Down-sample input as sun position change slowly compared to sampling rate
        sun = gps.loc[gps.fix_ok & gps.datetime_valid, ['latitude', 'longitude', 'gps_datetime', 'altitude']]
        sun = sun.reset_index().set_index('gps_datetime', drop=False).resample(sun_pos_rule).agg('first').dropna()
        sun['index'] = sun['index'].astype(int)
        if parallel:
            sun_list = list(sun.reindex(columns=['latitude', 'longitude', 'gps_datetime', 'altitude'])
                            .itertuples(name=None, index=False))
            with multiprocessing.Pool() as pool:
                sun['azimuth'], sun['elevation'] = zip(*tqdm(pool.imap(sun_position, sun_list),
                                                             'Computing SunPos', total=len(sun_list)))
        else:
            sun['azimuth'], sun['elevation'] = '', ''
            for i, row in tqdm(sun.iterrows(), 'Computing SunPos', total=len(sun)):
                sun.loc[i, 'azimuth'], sun.loc[i, 'elevation'] = \
                    sun_position((row.latitude, row.longitude, row.gps_datetime, row.altitude))
        sun.set_index('index', inplace=True)
        m_sun = pd.DataFrame(index=idx.ig)
        m_sun['azimuth'], m_sun['elevation'] = sun['azimuth'], sun['elevation']
        m_sun.azimuth = m_sun.azimuth.fillna(method='ffill')
        m_sun.elevation = m_sun.elevation.fillna(method='ffill')
        m_sun.loc[~(gps.fix_ok[idx.ig] & gps.datetime_valid[idx.ig]), ['azimuth', 'elevation']] = 'NAN'
        # Build frames
        heading_ship = ((gps.heading[idx.ig] - self.cfg_compass_zero) % 360).reset_index(drop=True)
        heading_sas = ((heading_ship - self.cfg_tower_zero + tower.position[idx.it].reset_index(drop=True)) % 360).apply(lambda x: f'{x:.2f}')
        heading_ship = heading_ship.apply(lambda x: f'{x:.2f}')
        heading_accuracy = gps.heading_accuracy[idx.ig].apply(lambda x: f'{x:.2f}').reset_index(drop=True)
        heading_motion = gps.heading_motion[idx.ig].apply(lambda x: f'{x:.1f}').reset_index(drop=True)
        heading_vehicle_accuracy = gps.heading_vehicle_accuracy[idx.ig].apply(lambda x: f'{x:.1f}').reset_index(drop=True)
        position = tower.position[idx.it].apply(lambda x: f'{x:.2f}').reset_index(drop=True)
        tower_status = pd.Series(['O'] * len(idx))
        tower_status[tower.stall_flag[idx.it].to_numpy()] = 'S'
        m_sun.reset_index(drop=True, inplace=True)
        frame = 'UMTWR,' + heading_sas + ',' + heading_ship + ',' + heading_accuracy + ',' + \
                heading_motion + ',' + heading_vehicle_accuracy + ',' + \
                position + ',' + tower_status + ',' + m_sun.azimuth + ',' + m_sun.elevation + '\r\n'
        return pd.DataFrame({'timestamp': idx.datetime.to_numpy(),
                             'frame': frame.str.encode('ascii')})

    @staticmethod
    def make_sathdr(values=dict()):
        """
        Make Satlantic File Header
        :param values: dictionary of headers
        :return:
        """
        keys = [b'CRUISE-ID', b'OPERATOR', b'INVESTIGATOR', b'AFFILIATION', b'CONTACT', b'EXPERIMENT',
                b'LATITUDE', b'LONGITUDE', b'ZONE', b'CLOUD_PERCENT', b'WAVE_HEIGHT', b'WIND_SPEED', b'COMMENT',
                b'DOCUMENT', b'STATION-ID', b'CAST', b'TIME-STAMP', b'MODE', b'TIMETAG', b'DATETAG', b'TIMETAG2',
                b'PROFILER', b'REFERENCE', b'PRO-DARK', b'REF-DARK']
        header = b''
        for k in keys:
            v = values[k] if k in values.keys() else b''
            sentence = b'SATHDR ' + v + b' (' + k + b')\r\n'
            if len(sentence) > 128:
                logger.warning(f'SATHDR {k} too long')
            sentence += b'\x00' * (128 - len(sentence))
            header += sentence
        return header

    def write(self, data, filename, meta=dict()):
        """
        Write HyperInSPACE formatted data

        :param data: data frame to write
        :param filename: output file name to write to
        :param meta: metadata to append to Satlantic file header
        :return:
        """
        # Make satlantic file header
        header = {b'ZONE': b'UTC',
               b'COMMENT': bytes(f'gps_orientation_on_ship={self.cfg_compass_zero};'
                                 f'indexing_table_orientation_on_ship={self.cfg_tower_zero};'
                                 f'optimal_angle_away_from_sun={self.cfg_target};', 'ascii')}
        min_ts = data.timestamp.min()
        if not pd.isna(min_ts):
            header[b'TIME-STAMP'] = bytes(min_ts.strftime('%a %b %d %H:%M:%S %Y'), 'ascii')
        if 'll_lat' in meta.keys() and 'ur_lat' in meta.keys():
            header[b'LATITUDE'] = bytes(f"{meta['ll_lat']}:{meta['ur_lat']}", 'ascii')
        if 'll_lon' in meta.keys() and 'ur_lon' in meta.keys():
            header[b'LONGITUDE'] = bytes(f"{meta['ll_lon']}:{meta['ur_lon']}", 'ascii')
        header = self.make_sathdr(header)
        # Format data
        body = b''.join([f + pack('!ii', d, t)[1:] for f, d, t in zip(
            data.frame,
            data.timestamp.dt.strftime('%Y%j').astype(int).to_list(),
            data.timestamp.dt.strftime('%H%M%S%f').str[:-3].astype(int).to_list()
        )])
        # Write to file
        with open(filename, mode='wb') as f:
            logger.debug(f'Writing {os.path.basename(filename)}')
            f.write(header)
            f.write(body)

    def run(self, path_in, path_out, file_out_prefix='pySAS_', mode='day', parallel=True,
            meta={}, compute_magnetic_declination=False):
        """
        Convert pySAS output to Satlantic formatted files for HyperInSPACE.
        Output files can be written by hours or days.
        Use UTC time to prepare files (no more solar time).

        :param path_in: path to directory containing pySAS output (gps, indexing table, and satlantic files).
        :param path_out: path to directory to write formatted data file (.raw).
        :param file_out_prefix: appended to each output file name
        :param mode: process data files by day ('day') or by hour ('hour'). Use UTC as timezone.
        :param parallel: compute sun position with all cores of computer
        :param meta: metadata to append to Satlantic file header
        :param compute_magnetic_declination: computationally intense. HyperInSPACE doesn't use it, so it can be skipped.
        :return:
        """
        # Read all data
        sat = self.read_sat(sorted(glob.glob(os.path.join(path_in, 'HyperSAS_*.bin'))))
        if sat is None:
            return
        gps = self.read_gps(sorted(glob.glob(os.path.join(path_in, 'GPS_*.csv'))))
        if gps is None:
            return
        twr = self.read_twr(sorted(glob.glob(os.path.join(path_in, 'IndexingTable_*.csv'))))
        if twr is None:
            return
        # Make HyperInSPACE specific frames
        gprmc = self.make_gprmc(gps, compute_magnetic_declination=compute_magnetic_declination)
        umtwr = self.make_umtwr(gps, twr, parallel=parallel)
        # Concatenate into single dataframe
        df = pd.concat([sat, gprmc, umtwr]).sort_values(by=['timestamp'], ignore_index=True)
        # Write data
        if mode in ['day', 'daily']:
            dt_start = df.timestamp.min().replace(hour=0, minute=0, second=0, microsecond=0)
            dt_end = df.timestamp.max() + timedelta(seconds=1)
            window = timedelta(days=1)
            dt_format = '%Y%m%d'
        elif mode in ['hour', 'hourly']:
            dt_start = df.timestamp.min().replace(minute=0, second=0, microsecond=0)
            dt_end = df.timestamp.max() + timedelta(seconds=1)
            window = timedelta(hours=1)
            dt_format = '%Y%m%d_%H%M%S'
        else:
            raise ValueError('writing mode not supported')
        if not os.path.exists(path_out):
            os.mkdir(path_out)
        dt = dt_start
        while dt < dt_end:
            sel = (dt <= gps.datetime) & (gps.datetime < dt + window)
            if sel.any():
                meta = {**meta,
                        'll_lat': gps.latitude[sel].min(), 'ur_lat': gps.latitude[sel].max(),
                        'll_lon': gps.longitude[sel].min(), 'ur_lon': gps.longitude[sel].max()}
            sel = (dt <= df.timestamp) & (df.timestamp < dt + window)
            if sel.any():
                self.write(df[sel], os.path.join(path_out, f'{file_out_prefix}{dt.strftime(dt_format)}.raw'), meta)
            dt += window


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Convert output from the University of Maine pySAS tower system to ")

    parser.add_argument('-v', '--version', action='version', version=f'{__file__} v{__version__}')
    parser.add_argument('--cal', nargs='?', required=True, help="HyperSAS & Es calibration files (.sip)")
    parser.add_argument('--cfg', nargs='?', required=True, help="pySAS configuration file (.ini).")
    parser.add_argument('-d', '--directory', required=True, nargs='?', help="path to directory of files to process")
    parser.add_argument('-m', '--mode', choices=['day', 'hour'],
                        help="process files day by day (default: day)")
    parser.add_argument('-f', '--file_out_prefix', nargs='?', help="prefix of output file when process directory")
    parser.add_argument('-e', '--experiment', nargs='?', help="SeaBASS name of experiment")
    parser.add_argument('-c', '--cruise', nargs='?', help="SeaBASS name of cruise")
    parser.add_argument('out', required=True, help="path to directory or filename of converted data.")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    logging.debug(args)

    c = Converter(args.cal, args.cfg)

    if args.file_out_prefix:
        file_out_prefix = args.file_out_prefix
    else:
        file_out_prefix = args.experiment if args.experiment is not None else ''
        file_out_prefix += '_' + args.cruise if args.cruise is not None else ''
    if file_out_prefix:
        kwargs = {'file_out_prefix': args.file_out_prefix + '_'}
    c.run(args.directory, args.out, mode=args.mode, **kwargs)
