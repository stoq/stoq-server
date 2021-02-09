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
"""

run with:

    gunicorn stoqserver.gunicorn -w 4 -b localhost:6971 -k gevent

"""

from stoqserver import activate_virtualenv
activate_virtualenv()

# This needs to be done ASAP, before any other imports.
from gevent import monkey
from psycogreen.gevent import patch_psycopg
monkey.patch_all()
patch_psycopg()

import stoq
from stoqserver import app
from stoqserver.main import setup_stoq, setup_logging

import sys
# sys.argv comes with the arguments passed to gunicorn, but stoq will not work well with those.
sys.argv = []

setup_stoq(register_station=True, name='stoqflask', version=stoq.version)
setup_logging(app_name='stoq-flask')

application = app.bootstrap_app(debug=False, multiclient=True)
