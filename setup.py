#!/usr/bin/env python3
import os
from setuptools import setup

#
# WIP: Not yet fully working / ready to be published on PyPI
#

DESC = """A slick sender rate limit policy daemon for Postfix implemented in Python3."""
with open(os.path.join(os.path.dirname(__file__), 'README.md')) as readme:
    README = readme.read()
data_files = []


def add_data_file(dir, file, check_dir=False, mkdir=False):
    path = os.path.join(dir, os.path.basename(file))
    if not os.path.isfile(path):
        if not check_dir or mkdir or os.path.isdir(dir):
            if mkdir:
                try:
                    os.mkdir(dir)
                except OSError:
                    pass
            data_files.append((dir, [file]))


# if install as root populate /etc
if os.getuid() == 0:
    add_data_file('/etc/logrotate.d', 'deployment/logrotate.d/policyd-rate-guard')
    add_data_file('/etc/systemd/system', 'deployment/systemd/policyd-rate-guard.service', check_dir=True)
    add_data_file('/etc/systemd/system', 'deployment/systemd/policyd-rate-guard-cleanup.service', check_dir=True)
    add_data_file('/etc/systemd/system', 'deployment/systemd/policyd-rate-guard-cleanup.timer', check_dir=True)
# else use user .config dir
# else:
#    conf_dir = os.path.expanduser("~/.config/")
#    add_data_file(conf_dir, 'policyd_rate_guard/policyd-rate-guard.yaml', mkdir=True)

setup(
    name='policyd-rate-guard',
    version='0.5.0',
    description=DESC,
    long_description=README,
    author='Onlime GmbH',
    author_email='info@onlime.ch',
    license='GPLv3',
    url='https://github.com/nitmir/policyd-rate-limit',
    download_url="https://github.com/onlime/policyd-rate-guard/releases/latest",
    packages=['policyd_rate_guard', 'policyd_rate_guard.tests'],
    keywords=['Postfix', 'rate', 'limit', 'guard', 'email'],
    scripts=['run.py'],
    data_files=data_files,
    classifiers=[
        'Environment :: No Input/Output (Daemon)',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Topic :: Communications :: Email :: Mail Transport Agents',
        'Topic :: Communications :: Email :: Filters',
    ],
    install_requires=["PyYAML >= 3.11"],
    zip_safe=False,
)
