# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2020 Stoq Tecnologia <http://www.stoq.com.br>
# All rights reserved
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., or visit: http://www.gnu.org/.
#
# Author(s): Stoq Team <dev@stoq.com.br>
#

import os
import platform
import sys

from setuptools import find_packages, setup

import stoqserver

install_requires = [
    "babel",
    "flask >= 0.10.1, < 1",
    "flask-restful >= 0.3.4",
    "gevent >= 1.1.0",
    "netifaces",
    "psutil >= 3.4.2",
    "psycogreen",
    "raven",
    "requests >= 2.2",
    "tzlocal >= 1.2.2",
]

data_files = []
if 'bdist_egg' not in sys.argv and platform.system() != "Windows":
    data_files = [
        ('/etc/sudoers.d', [os.path.join('data', 'sudoers.d', 'stoqserver')]),
        ('/etc/supervisor/conf.d', [os.path.join('data', 'supervisor', 'stoqserver.conf')]),
    ]

setup(
    name='stoqserver',
    author="Stoq Team",
    author_email="dev@stoq.com.br",
    description="Stoq server",
    url="http://www.stoq.com.br",
    license="GNU LGPL 2.1 (see COPYING)",
    long_description=("Service that provides a bridge between Stoq and "
                      "stoq.link, along with other usefullnesses."),
    version=stoqserver.version_str,
    packages=find_packages(),
    install_requires=install_requires,
    scripts=['bin/stoqserver'],
    zip_safe=True,
    include_package_data=True,
    data_files=data_files,
)