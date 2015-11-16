# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2014 Async Open Source <http://www.async.com.br>
## All rights reserved
##

import os

_ = lambda s: s


#
#  General
#

APP_DIR = os.path.join(os.environ['HOME'], '.stoq')
APP_EGGS_DIR = os.path.join(APP_DIR, 'eggs')
APP_CONF_FILE = os.path.join(APP_DIR, 'stoq.conf')

SERVER_NAME = _('Stoq Server')
SERVER_EGGS = ['kiwi.egg', 'stoqdrivers.egg', 'stoq.egg']
SERVER_EXECUTABLE_EGG = 'stoq.egg'
SERVER_AVAHI_PORT = 6970
SERVER_DAEMON_PORT = 6971

#
#  Avahi
#

AVAHI_STYPE = '_stoqserver._tcp'
AVAHI_DOMAIN = ''
AVAHI_HOST = ''
