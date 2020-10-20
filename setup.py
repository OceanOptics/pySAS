import setuptools
import os

version = None
with open(os.path.join(os.path.dirname(__file__), 'pySAS', '__init__.py')) as f:
    for line in f:
        v = line.split('=')
        if v[0].strip() == '__version__':
            version = v[1].strip().strip('\'').strip('\"')
            break

with open(os.path.join(os.path.dirname(__file__),'requirements.txt')) as f:
    requirements = f.read().splitlines()

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pySAS",
    version=version,
    author="Nils Haentjens",
    author_email="nils.haentjens@maine.edu",
    description="Autonomous above water radiometric measurements",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/doizuc/pySAS/",
    packages=['pySAS'],
    package_dir={'pySAS': 'pySAS'},
    package_data={'pySAS': ['assets/*.css', 'assets/*.map']},
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
