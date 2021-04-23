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

from contextlib import suppress
from enum import Enum
from typing import Dict
import json
import logging

from flask import make_response, request, Response
from psycopg2 import DataError
import redis
from werkzeug.local import LocalProxy

from stoqlib.api import api
from stoqlib.lib.configparser import get_config
from stoqlib.lib.decorators import cached_function
from stoqlib.domain.station import BranchStation
from stoqserver.lib.baseresource import BaseResource
from ..signals import EventStreamEstablishedEvent, TefCheckPendingEvent
from ..utils import JsonEncoder

log = logging.getLogger(__name__)

STREAM_BROKEN = b'STREAM_BROKEN'
STREAM_FORCE_CLOSE = b'STREAM_FORCE_CLOSE'
STREAM_ALL_BRANCHES = b'STREAM_ALL_BRANCHES'


@cached_function()
def get_redis_server():
    config = get_config()
    assert config

    url = config.get('General', 'redis_server') or 'redis://localhost'
    return redis.from_url(url)

redis_server = LocalProxy(get_redis_server)


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

    routes = ['/stream']

    @classmethod
    def add_event(cls, data, station=None):
        """If station specified, put a event only on the client stream.
        Otherwise, put it in all streams
        """
        payload = json.dumps(data, cls=JsonEncoder)
        if station:
            if station.is_api:
                return

            receivers = redis_server.publish(station.id, payload)
            if receivers == 0:
                raise EventStreamUnconnectedStation
            return

        redis_server.publish(STREAM_ALL_BRANCHES, payload)

    @classmethod
    def ask_question(cls, station, question):
        """Sends a question down the stream"""
        log.info('Asking %s question: %s', station.name, question)
        cls.add_event({
            'type': 'TEF_ASK_QUESTION',
            'data': question,
        }, station=station)

        log.info('Waiting tef reply')

        redis_server.hset('waiting', station.id, 1)
        # This call will block until some other request puts a reply on this list
        reply = json.loads(redis_server.blpop('reply-%s' % station.id, timeout=0)[1].decode())
        redis_server.hdel('waiting', station.id)

        log.info('Got tef reply: %s', reply)
        return reply

    @classmethod
    def add_event_reply(cls, station_id, reply):
        """Puts a reply from the frontend"""
        log.info('Got reply from %s: %s', station_id, reply)
        assert redis_server.llen('reply-%s' % station_id) == 0
        assert redis_server.hexists('waiting', station_id)

        redis_server.lpush('reply-%s' % station_id, reply)

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

    def _loop(self, stream: redis.client.PubSub, station_id):
        while True:
            data = stream.get_message(timeout=10)
            if data is None:
                yield "data: null\n\n"
                continue

            if data['type'] == 'subscribe':
                continue

            if data['data'] == STREAM_FORCE_CLOSE:
                log.info('Stream for station %s changed. Closing old stream', station_id)
                break

            yield "data: " + data['data'].decode() + "\n\n"
        log.info('Closed event stream for %s', station_id)

    def get(self):
        store = api.new_store()
        station = self.get_current_station(store, token=request.args['token'])
        if not station:
            log.info('Invalid token for event stream: %s', request.args['token'])
            return

        log.info('Estabilished event stream for %s', station.id)

        # Break any connections that are still listening on this station's stream
        redis_server.publish(station.id, STREAM_FORCE_CLOSE)

        stream = redis_server.pubsub()
        stream.subscribe(station.id)
        stream.subscribe(STREAM_ALL_BRANCHES)

        if redis_server.hexists('waiting', station.id):
            # There is a new stream for this station, but we were currently waiting for a reply from
            # the same station in the previous event stream. Put an invalid reply there, and clear
            # the flag so that the station can continue working
            redis_server.lpush('reply-%s' % station.id, STREAM_BROKEN)
            redis_server.hdel('waiting', station.id)

        # If we dont put one event, the event stream does not seem to get stabilished in the browser
        self.add_event({}, station)

        EventStreamEstablishedEvent.send(station)

        # This is the best time to check if there are pending transactions, since the frontend just
        # stabilished a connection with the backend (thats us).
        has_canceled = TefCheckPendingEvent.send()
        if has_canceled and has_canceled[0][1]:
            EventStream.add_event({'type': 'TEF_WARNING_MESSAGE',
                                   'message': ('Última transação TEF não foi efetuada.'
                                               ' Favor reter o Cupom.')},
                                  station=station)
            EventStream.add_event({'type': 'CLEAR_SALE'}, station=station)
        station_id = station.id
        store.close()
        return Response(self._loop(stream, station_id), mimetype="text/event-stream")

    def post(self):
        station_id = request.values.get('station_id')
        data = request.json

        if not station_id:
            EventStream.add_event({
                'type': 'EVENT_RECEIVED',
                'data': data,
            })
            return ('event put in streams from all connected stations', 200)

        with api.new_store() as store:
            try:
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
