prepSAS
=======

*Converts data acquired with pySAS to a single file following Satlantic format.*

prepSAS takes in input the three data files from pySAS (HyperSAS_<>.bin, GPS_<>.csv, and IndexingTable_<>.csv), the HyperSAS and Es calibration files (typically .sip), and the pySAS configuration file (pySAS_cfg.ini). It reformats the data into a single .raw file following Satlantic format which can be ingested by HyperInSpace to process the data to a higher level for scientific use.

The tower and GPS parameters recorded are inserted into the $GPRMC frames (standard NMEA0183) and a custom frame (UMTWR). The UMTWR frames are variable length frames with each field separated by commas. The parameters are ordered as follows:

+ HEADING	SAS
+ HEADING	SHIP
+ HEADNIG_ACCURACY	SHIP
+ HEADING	MOTION
+ HEADING_ACCURACY	MOTION
+ POSITION	TOWER
+ STATUS	TOWER
+ AZIMUTH	SUN
+ ELEVATION	SUN

Example of UMTWR data frame:

    UMTWR,292.21,292.21,0.32,0.0,180.0,0.00,O,203.5,22.7


The SATHDR frames are appended at the top of the file.


Example of commands to run the script:

    # Run a single file
    python prepSAS.py -s 'test_data/pySAS002/HyperSAS_20201120_175620.bin' -g 'test_data/pySAS002/GPS_20201120_175616.csv' -t 'test_data/pySAS002/IndexingTable_20201120_175616.csv' --cal 'test_data/pySAS002/HyperSAS_Es_20200212.sip' --cfg 'test_data/pySAS002/pysas_cfg_002.ini' 'test_data/pySAS002/UMSAS002_20201120_175620.raw'

    # Run all files within a directory
    python prepSAS.py -d 'test_data/pySAS002/' --cal 'test_data/pySAS002/HyperSAS_Es_20200212.sip' --cfg 'test_data/pySAS002/pysas_cfg_002.ini' 'test_data/pySAS002'

    # Help
    python prepSAS.py -h

    # Version
    python prepSAS.py -v
