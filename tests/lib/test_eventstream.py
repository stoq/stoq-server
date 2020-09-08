from unittest import mock
import json

from gevent.event import Event
from gevent.queue import Queue
import pytest

from stoqserver.lib.eventstream import DeviceType, EventStream, EventStreamBrokenException


@pytest.fixture
def event_stream():
    class TestEventStream(EventStream):
        pass
    return TestEventStream


@pytest.fixture
def unconnected_station(event_stream, current_station):
    event_stream._streams.pop(current_station.id, None)
    return current_station


@pytest.fixture
def connected_station(event_stream, current_station):
    event_stream._streams[current_station.id] = Queue()
    return current_station


@pytest.fixture
def stream_token(client):
    return client.auth_token.split('Bearer ')[1]


def test_add_event_device_status_changed_wont_fail(event_stream, unconnected_station):
    event_stream.add_event_device_status_changed(unconnected_station, DeviceType.PRINTER, True)


def test_add_event_device_status_changed_with_opened_drawer(event_stream, connected_station):
    event_stream.add_event_device_status_changed(connected_station, DeviceType.DRAWER, True)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {'type': 'DRAWER_ALERT_OPEN'}


def test_add_event_device_status_changed_with_closed_drawer(event_stream, connected_station):
    event_stream.add_event_device_status_changed(connected_station, DeviceType.DRAWER, False)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {'type': 'DRAWER_ALERT_CLOSE'}


def test_add_event_device_status_changed_with_drawer_check_error(event_stream, connected_station):
    event_stream.add_event_device_status_changed(connected_station, DeviceType.DRAWER, None)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {'type': 'DRAWER_ALERT_ERROR'}


@pytest.mark.parametrize('device_type', (DeviceType.PRINTER, DeviceType.SAT, DeviceType.PINPAD))
@pytest.mark.parametrize('device_status', (True, False))
def test_add_event_device_status_changed_succeeds(event_stream, connected_station,
                                                  device_type, device_status):
    event_stream.add_event_device_status_changed(connected_station, device_type, device_status)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {
        'type': 'DEVICE_STATUS_CHANGED',
        'device': device_type.value,
        'status': device_status
    }


@mock.patch('stoqserver.lib.eventstream.EventStream._loop')
def test_get_event_stream_with_waiting_reply(
    mock_loop, event_stream, connected_station,
    client, stream_token
):
    mock_loop.return_value = json.dumps({})
    event_stream._replies[connected_station.id] = Queue()
    event_stream._waiting_reply[connected_station.id] = Event()
    event_stream._waiting_reply[connected_station.id].set()

    response = client.get('/stream', query_string={'token': stream_token})

    assert EventStreamBrokenException in event_stream._replies[connected_station.id]
    assert not event_stream._waiting_reply[connected_station.id].is_set()
    assert response.status_code == 200
    stream = event_stream._streams[connected_station.id]
    mock_loop.assert_called_once_with(stream, connected_station.id)


@mock.patch('stoqserver.lib.eventstream.EventStream._loop')
def test_get_event_stream_does_not_replace_replies(
    mock_loop, event_stream, connected_station,
    client, stream_token
):
    mock_loop.return_value = json.dumps({})
    event_stream._replies[connected_station.id] = 'test_reply'

    response = client.get('/stream', query_string={'token': stream_token})

    assert event_stream._replies[connected_station.id] == 'test_reply'
    assert response.status_code == 200
    stream = event_stream._streams[connected_station.id]
    mock_loop.assert_called_once_with(stream, connected_station.id)


@mock.patch('stoqserver.lib.eventstream.api.new_store')
@mock.patch('stoqserver.lib.eventstream.EventStream._loop')
@mock.patch('stoqserver.lib.eventstream.EventStreamEstablishedEvent', autospec=True)
def test_get_event_stream(
    mock_event_stream_established_event, mock_loop, mock_new_store,
    event_stream, connected_station, client,
    stream_token, store
):
    mock_new_store.return_value = store
    mock_loop.return_value = json.dumps({})

    response = client.get('/stream', query_string={'token': stream_token})

    mock_event_stream_established_event.send.assert_called_once_with(connected_station)
    assert response.status_code == 200
    stream = event_stream._streams[connected_station.id]
    mock_loop.assert_called_once_with(stream, connected_station.id)
