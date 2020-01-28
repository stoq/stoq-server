from gevent.queue import Queue
import pytest

from stoqserver.lib.eventstream import EventStream, DeviceType


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


def test_put_device_status_changed_wont_fail(event_stream, unconnected_station):
    event_stream.put_device_status_changed(unconnected_station, DeviceType.PRINTER, True)


def test_put_device_status_changed_with_opened_drawer(event_stream, connected_station):
    event_stream.put_device_status_changed(connected_station, DeviceType.DRAWER, True)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {'type': 'DRAWER_ALERT_OPEN'}


def test_put_device_status_changed_with_closed_drawer(event_stream, connected_station):
    event_stream.put_device_status_changed(connected_station, DeviceType.DRAWER, False)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {'type': 'DRAWER_ALERT_CLOSE'}


def test_put_device_status_changed_with_drawer_check_error(event_stream, connected_station):
    event_stream.put_device_status_changed(connected_station, DeviceType.DRAWER, None)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {'type': 'DRAWER_ALERT_ERROR'}


@pytest.mark.parametrize('device_type', (DeviceType.PRINTER, DeviceType.SAT, DeviceType.PINPAD))
@pytest.mark.parametrize('device_status', (True, False))
def test_put_device_status_changed_succeeds(event_stream, connected_station,
                                            device_type, device_status):
    event_stream.put_device_status_changed(connected_station, device_type, device_status)

    station_stream = event_stream._streams[connected_station.id]
    assert station_stream.get() == {
        'type': 'DEVICE_STATUS_CHANGED',
        'device': device_type.value,
        'status': device_status
    }
