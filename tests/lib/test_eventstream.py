from unittest import mock
import json

import pytest

from stoqserver.lib.eventstream import DeviceType, EventStream, STREAM_BROKEN

import redis
redis_server = redis.Redis('localhost')


@pytest.fixture
def event_stream():
    class TestEventStream(EventStream):
        pass
    return TestEventStream


@pytest.fixture
def unconnected_station(event_stream, current_station):
    return current_station


@pytest.fixture
def stream(event_stream, current_station):
    stream = redis_server.pubsub()
    stream.subscribe(current_station.id)
    # We need to get the subscribe message
    message = stream.get_message(timeout=30)
    assert message
    return stream


@pytest.fixture
def stream_token(client):
    return client.auth_token.split('Bearer ')[1]


def test_add_event_device_status_changed_wont_fail(event_stream, unconnected_station):
    event_stream.add_event_device_status_changed(unconnected_station, DeviceType.PRINTER, True)


def test_add_event_device_status_changed_with_opened_drawer(event_stream, current_station, stream):
    event_stream.add_event_device_status_changed(current_station, DeviceType.DRAWER, True)
    message = stream.get_message(timeout=30)
    assert json.loads(message['data'].decode()) == {'type': 'DRAWER_ALERT_OPEN'}


def test_add_event_device_status_changed_with_closed_drawer(event_stream, current_station, stream):
    event_stream.add_event_device_status_changed(current_station, DeviceType.DRAWER, False)
    message = stream.get_message(timeout=30)
    assert json.loads(message['data'].decode()) == {'type': 'DRAWER_ALERT_CLOSE'}


def test_add_event_device_status_changed_with_drawer_check_error(event_stream, current_station,
                                                                 stream):
    event_stream.add_event_device_status_changed(current_station, DeviceType.DRAWER, None)

    message = stream.get_message(timeout=30)
    assert json.loads(message['data'].decode()) == {'type': 'DRAWER_ALERT_ERROR'}


@pytest.mark.parametrize('device_type', (DeviceType.PRINTER, DeviceType.SAT, DeviceType.PINPAD))
@pytest.mark.parametrize('device_status', (True, False))
def test_add_event_device_status_changed_succeeds(event_stream, current_station, stream,
                                                  device_type, device_status):
    event_stream.add_event_device_status_changed(current_station, device_type, device_status)

    message = stream.get_message(timeout=30)
    assert json.loads(message['data'].decode()) == {
        'type': 'DEVICE_STATUS_CHANGED',
        'device': device_type.value,
        'status': device_status
    }


@mock.patch('stoqserver.lib.eventstream.EventStream._loop')
def test_get_event_stream_with_waiting_reply(
    mock_loop, event_stream, current_station, stream,
    client, stream_token
):
    mock_loop.return_value = json.dumps({})
    redis_server.hset('waiting', current_station.id, 1)

    response = client.get('/stream', query_string={'token': stream_token})

    assert redis_server.blpop('reply-%s' % current_station.id)[1] == STREAM_BROKEN
    assert not redis_server.hexists('waiting', current_station.id)
    assert response.status_code == 200


@mock.patch('stoqserver.lib.eventstream.EventStream._loop')
def test_get_event_stream_does_not_replace_replies(
    mock_loop, event_stream, current_station, stream,
    client, stream_token
):
    mock_loop.return_value = json.dumps({})
    redis_server.lpush('reply-%s' % current_station.id, 'test_reply')

    response = client.get('/stream', query_string={'token': stream_token})

    assert redis_server.llen('reply-%s' % current_station.id) == 1
    assert redis_server.blpop('reply-%s' % current_station.id)[1] == b'test_reply'
    assert response.status_code == 200


@mock.patch('stoqserver.lib.eventstream.api.new_store')
@mock.patch('stoqserver.lib.eventstream.EventStream._loop')
@mock.patch('stoqserver.lib.eventstream.EventStreamEstablishedEvent', autospec=True)
def test_get_event_stream(
    mock_event_stream_established_event, mock_loop, mock_new_store,
    event_stream, current_station, stream, client,
    stream_token, store
):
    mock_new_store.return_value = store
    mock_loop.return_value = json.dumps({})

    response = client.get('/stream', query_string={'token': stream_token})

    mock_event_stream_established_event.send.assert_called_once_with(current_station)
    assert response.status_code == 200
