import setuptools
from pySAS import __version__

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pySAS",
    version=__version__,
    author="Nils Haentjens",
    author_email="nils.haentjens@maine.edu",
    description="Autonomous above water radiometric measurements",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/doizuc/pySAS/",
    packages=setuptools.find_packages(),
    install_requires=['dash>=1.9.1', 'dash-bootstrap-components', 'geomag', 'gpiozero',
                      'numpy', 'pyserial>=3.4', 'pysolar==0.8', 'pytz', 'ubxtranslator', 'pySatlantic'],
    python_requires='>=3.8',
    license='GNU AGPLv3',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research"
    ]
)