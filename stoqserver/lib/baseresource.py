# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2020 Stoq Tecnologia <https://www.stoq.com.br>
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

import decimal
import json
import logging

import gevent
from flask import request
from flask_restful import Resource
from serial.serialutil import SerialException

from stoqdrivers.exceptions import InvalidReplyException, PrinterError
from stoqlib.api import api
from stoqlib.domain.devices import DeviceSettings
from stoqlib.domain.token import AccessToken
from stoqlib.lib.pluginmanager import get_plugin_manager, PluginError
from ..app import is_multiclient
from .lock import printer_lock

log = logging.getLogger(__name__)


def get_plugin(manager, name):
    try:
        return manager.get_plugin(name)
    except PluginError:
        return None


class BaseResource(Resource):

    routes = []

    def get_json(self):
        if not request.data:
            return None
        return json.loads(request.data.decode(), parse_float=decimal.Decimal)

    def get_arg(self, attr, default=None):
        """Get the attr from querystring, form data or json"""
        # This is not working on all versions.
        if self.get_json():
            return self.get_json().get(attr, None)

        return request.form.get(attr, request.args.get(attr, default))

    def get_current_user(self, store):
        auth = request.headers.get('Authorization', '').split('Bearer ')
        token = AccessToken.get_by_token(store=store, token=auth[1])
        return token and token.user

    def get_current_station(self, store, token=None):
        if not token:
            auth = request.headers.get('Authorization', '').split('Bearer ')
            token = auth[1]
        token = AccessToken.get_by_token(store=store, token=token)
        return token and token.station

    def get_current_branch(self, store):
        station = self.get_current_station(store)
        return station and station.branch

    @classmethod
    def ensure_printer(cls, station, retries=20):
        # In multiclient mode there is no local printer
        if is_multiclient():
            return

        assert printer_lock.locked()

        device = DeviceSettings.get_by_station_and_type(station.store, station,
                                                        DeviceSettings.NON_FISCAL_PRINTER_DEVICE)
        if not device:
            # If we have no printer configured, there's nothing to ensure
            return

        # There is no need to lock the printer here, since it should already be locked by the
        # calling site of this method.
        # Test the printer to see if its working properly.
        printer = None
        try:
            printer = api.device_manager.printer
            return printer.is_drawer_open()
        except (SerialException, InvalidReplyException, PrinterError):
            if printer:
                printer._port.close()
            api.device_manager._printer = None
            for i in range(retries):
                log.info('Printer check failed. Reopening: %s', i)
                try:
                    printer = api.device_manager.printer
                    printer.is_drawer_open()
                    break
                except (SerialException, PrinterError):
                    gevent.sleep(1)
            else:
                # Reopening printer failed. re-raise the original exception
                raise

            # Invalidate the printer in the plugins so that it re-opens it
            manager = get_plugin_manager()

            # nfce does not need to reset the printer since it does not cache it.
            sat = get_plugin(manager, 'sat')
            if sat and sat.ui:
                sat.ui.printer = None

            nonfiscal = get_plugin(manager, 'nonfiscal')
            if nonfiscal and nonfiscal.ui:
                nonfiscal.ui.printer = printer

            return printer.is_drawer_open()
