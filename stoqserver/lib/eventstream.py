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

from contextlib import suppress
from enum import Enum
from typing import Dict
import json
import logging

from flask import make_response, request, Response
from gevent.event import Event
from gevent.queue import Queue, Empty
from psycopg2 import DataError

from ..signals import TefCheckPendingEvent
from ..utils import JsonEncoder
from stoqlib.api import api
from stoqlib.domain.station import BranchStation
from stoqserver.lib.baseresource import BaseResource

log = logging.getLogger(__name__)


# pyflakes
Dict


DRAWER_STATUS_TO_EVENT_TYPE_MAP = {
    True: 'DRAWER_ALERT_OPEN',
    False: 'DRAWER_ALERT_CLOSE',
    None: 'DRAWER_ALERT_ERROR',
}


class DeviceType(Enum):
    DRAWER = 'drawer'
    PRINTER = 'printer'
    SAT = 'sat'
    PINPAD = 'pinpad'


class EventStreamUnconnectedStation(Exception):
    pass


class EventStreamBrokenException(Exception):
    pass


class EventStream(BaseResource):
    """A stream of events from this server to the application.

    Callsites can use EventStream.add_event(event) to send a message from the server to the client
    asynchronously.

    Note that there should be only one client connected at a time. If more than one are connected,
    all of them will receive all events
    """

    # Some queues that messages will be added to and latter be sent to the connected stations in the
    # stream. Note that there can be only one client for each station
    _streams = {}  # type: Dict[str, Queue]

    # The replies that is comming from the station.
    _replies = {}  # type: Dict[str, Queue]

    # Indicates if there is a payment process waiting for a reply from a station.
    _waiting_reply = {}  # type: Dict[str, Event]

    routes = ['/stream']

    @classmethod
    def add_event(cls, data, station=None):
        """If station specified, put a event only on the client stream.
        Otherwise, put it in all streams
        """

        if station:
            if not station.id in cls._streams:
                raise EventStreamUnconnectedStation

            return cls._streams[station.id].put(data)

        for stream in cls._streams.values():
            stream.put(data)

    @classmethod
    def ask_question(cls, station, question):
        """Sends a question down the stream"""
        log.info('Asking %s question: %s', station.name, question)
        cls.add_event({
            'type': 'TEF_ASK_QUESTION',
            'data': question,
        }, station=station)

        log.info('Waiting tef reply')
        cls._waiting_reply[station.id].set()
        reply = cls._replies[station.id].get()
        cls._waiting_reply[station.id].clear()
        log.info('Got tef reply: %s', reply)
        return reply

    @classmethod
    def add_event_reply(cls, station_id, reply):
        """Puts a reply from the frontend"""
        log.info('Got reply from %s: %s', station_id, reply)
        assert cls._replies[station_id].empty()
        assert cls._waiting_reply[station_id].is_set()

        return cls._replies[station_id].put(reply)

    @classmethod
    def _get_event_for_device(cls, device_type: DeviceType, device_status: bool):
        if device_type == DeviceType.DRAWER:
            return {
                'type': DRAWER_STATUS_TO_EVENT_TYPE_MAP[device_status],
            }

        if device_type in [DeviceType.PRINTER, DeviceType.SAT, DeviceType.PINPAD]:
            return {
                'type': 'DEVICE_STATUS_CHANGED',
                'device': device_type.value,
                'status': device_status,
            }

    @classmethod
    def add_event_device_status_changed(cls, station, device_type: DeviceType, device_status: bool):
        """Put a device status changed event in a station stream"""
        event = cls._get_event_for_device(device_type, device_status)
        if not event:
            return

        with suppress(EventStreamUnconnectedStation):
            cls.add_event(event, station=station)

    def _loop(self, stream: Queue, station_id):
        while True:
            try:
                data = stream.get(timeout=2)
            except Empty:
                if self._streams[station_id] != stream:
                    log.info('Stream for station %s changed. Closing old stream', station_id)
                    break

                continue

            yield "data: " + json.dumps(data, cls=JsonEncoder) + "\n\n"
        log.info('Closed event stream for %s', station_id)

    def get(self):
        stream = Queue()
        station = self.get_current_station(api.get_default_store(), token=request.args['token'])
        log.info('Estabilished event stream for %s', station.id)
        self._streams[station.id] = stream

        # Don't replace the reply queue and waiting reply flag
        self._replies.setdefault(station.id, Queue(maxsize=1))
        self._waiting_reply.setdefault(station.id, Event())

        if self._waiting_reply[station.id].is_set():
            # There is a new stream for this station, but we were currently waiting for a reply from
            # the same station in the previous event stream. Put an invalid reply there, and clear
            # the flag so that the station can continue working
            self._replies[station.id].put(EventStreamBrokenException)
            self._waiting_reply[station.id].clear()

        # If we dont put one event, the event stream does not seem to get stabilished in the browser
        stream.put(json.dumps({}))

        # This is the best time to check if there are pending transactions, since the frontend just
        # stabilished a connection with the backend (thats us).
        has_canceled = TefCheckPendingEvent.send()
        if has_canceled and has_canceled[0][1]:
            EventStream.add_event({'type': 'TEF_WARNING_MESSAGE',
                                   'message': ('Última transação TEF não foi efetuada.'
                                               ' Favor reter o Cupom.')},
                                  station=station)
            EventStream.add_event({'type': 'CLEAR_SALE'}, station=station)
        return Response(self._loop(stream, station.id), mimetype="text/event-stream")

    def post(self):
        station_id = request.values.get('station_id')
        data = request.json

        if not station_id:
            EventStream.add_event({
                'type': 'EVENT_RECEIVED',
                'data': data,
            })
            return ('event put in streams from all connected stations', 200)

        try:
            store = api.new_store()
            station = store.get(BranchStation, station_id)
        except DataError as err:
            return make_response(str(err), 400)

        if not station:
            return make_response('station not found', 404)

        try:
            EventStream.add_event({'type': 'EVENT_RECEIVED', 'data': data}, station=station)
            return make_response('event put in stream from station %s' % station_id, 200)
        except EventStreamUnconnectedStation as err:
            return make_response(str(err), 400)
