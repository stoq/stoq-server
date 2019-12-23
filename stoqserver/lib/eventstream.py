# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2019 Stoq Tecnologia <https://www.stoq.com.br>
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
# Author(s): Stoq Team <stoq-devel@async.com.br>
#

import json

from flask import request, Response
from gevent.queue import Queue
from gevent.event import Event

from stoqlib.api import api
from stoqserver.lib.baseresource import BaseResource
from ..signals import TefCheckPendingEvent
from ..utils import JsonEncoder


class EventStream(BaseResource):
    """A stream of events from this server to the application.

    Callsites can use EventStream.put(event) to send a message from the server to the client
    asynchronously.

    Note that there should be only one client connected at a time. If more than one are connected,
    all of them will receive all events
    """
    _streams = {}
    has_stream = Event()

    routes = ['/stream']

    @classmethod
    def put(cls, station, data):
        """Put a event only on the client stream"""
        # Wait until we have at least one stream
        cls.has_stream.wait()

        # Put event only on client stream
        stream = cls._streams.get(station.id)
        if stream:
            stream.put(data)

    @classmethod
    def put_all(cls, data):
        """Put a event in all streams"""
        # Wait until we have at least one stream
        cls.has_stream.wait()

        # Put event in all streams
        for stream in cls._streams.values():
            stream.put(data)

    def _loop(self, stream):
        while True:
            data = stream.get()
            yield "data: " + json.dumps(data, cls=JsonEncoder) + "\n\n"

    def get(self):
        stream = Queue()
        station = self.get_current_station(api.get_default_store(), token=request.args['token'])
        self._streams[station.id] = stream
        self.has_stream.set()

        # If we dont put one event, the event stream does not seem to get stabilished in the browser
        stream.put(json.dumps({}))

        # This is the best time to check if there are pending transactions, since the frontend just
        # stabilished a connection with the backend (thats us).
        has_canceled = TefCheckPendingEvent.send()
        if has_canceled and has_canceled[0][1]:
            EventStream.put(station, {'type': 'TEF_WARNING_MESSAGE',
                                      'message': ('Última transação TEF não foi efetuada.'
                                                  ' Favor reter o Cupom.')})
            EventStream.put(station, {'type': 'CLEAR_SALE'})
        return Response(self._loop(stream), mimetype="text/event-stream")
