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
from stoqlib.lib.osutils import get_application_dir

_ = lambda s: s


#
#  General
#

APP_DIR = get_application_dir()
APP_EGGS_DIR = os.path.join(APP_DIR, 'eggs')
APP_CONF_FILE = os.path.join(APP_DIR, 'stoq.conf')
APP_BACKUP_DIR = os.path.join(APP_DIR, 'scripts')

SERVER_NAME = _('Stoq Server')
SERVER_EGGS = ['kiwi.egg', 'stoqdrivers.egg', 'stoq.egg']
# FIXME: Windows
SERVER_EGGS = []
SERVER_EXECUTABLE_EGG = 'stoq.egg'
SERVER_AVAHI_PORT = 6969
SERVER_XMLRPC_PORT = 6970
SERVER_FLASK_PORT = 6971

#
#  Avahi
#

AVAHI_STYPE = '_stoqserver._tcp'
AVAHI_DOMAIN = ''
AVAHI_HOST = ''
