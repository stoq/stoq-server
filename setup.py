# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2015 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import os
from setuptools import setup, find_packages


PACKAGE = 'stoqserver'

scripts = [
    'bin/stoqserver',
]
data_files = [
    (os.path.join(os.sep, 'etc', 'supervisor', 'conf.d'),
     [os.path.join('data', 'supervisor', 'stoqserver.conf')]),
]

with open('requirements.txt') as f:
    install_requires = [l.strip() for l in f.readlines() if
                        l.strip() and not l.startswith('#')]

setup(
    name=PACKAGE,
    author="Stoq Team",
    author_email="stoq-devel@async.com.br",
    version="0.1",
    packages=find_packages(),
    data_files=data_files,
    install_requires=install_requires,
    scripts=scripts,
    zip_safe=True,
)
