import PyInstaller.__main__
from prepSAS import __version__
import os
import platform

if platform.system() == 'Windows':
    # Windows
    OS_OPERATOR = ';'
    ICON_EXT = 'ico'
    DIST_PATH = 'dist_windows'
    GEOMAG_WMM_PATH = r'Z:\usr\local\Caskroom\miniconda\base\envs\Inlinino\lib\python3.8\site-packages\geomag\WMM.COF'
elif platform.system() == 'Darwin':
    # macOS
    OS_OPERATOR = ':'
    ICON_EXT = 'icns'
    DIST_PATH = 'dist_darwin'
    GEOMAG_WMM_PATH = r'/usr/local/Caskroom/miniconda/base/envs/Inlinino/lib/python3.8/site-packages/geomag/WMM.COF'
    # TODO add version number in plist of spec file (CFBundleVersion)
    # https://pyinstaller.readthedocs.io/en/stable/spec-files.html?highlight=info_plist
    # https://developer.apple.com/library/archive/documentation/General/Reference/InfoPlistKeyReference/Articles/CoreFoundationKeys.html#//apple_ref/doc/uid/20001431-102364
else:
    # Linux
    OS_OPERATOR = ':'
    ICON_EXT = 'ico'
    DIST_PATH = 'dist_linux'
    GEOMAG_WMM_PATH = r'/usr/local/Caskroom/miniconda/base/envs/Inlinino/lib/python3.8/site-packages/geomag/WMM.COF'

PyInstaller.__main__.run([
    f'--name=prepSAS-v{__version__}',
    f'--add-data={os.path.join("README.md")}{OS_OPERATOR}.',
    f'--add-data={GEOMAG_WMM_PATH}{OS_OPERATOR}geomag',  # geomag WMM.COF file
    f'--add-data=resources{OS_OPERATOR}resources',
    f'--icon={os.path.join("resources", f"prepSAS.{ICON_EXT}")}',
    '--osx-bundle-identifier=com.umaine.sms.prepsas',
    f'--distpath={DIST_PATH}',
    '--clean',
    '--noconfirm',
    # '--debug=all',
    # '--windowed',
    '--console',
    # '--onefile',
    'gui.py'
])
