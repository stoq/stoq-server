import pytest
import socket

from unittest import mock

from stoqdrivers.exceptions import PrinterError
from stoqserver.lib.checks import check_drawer


@pytest.mark.parametrize('error', (socket.timeout, PrinterError))
@mock.patch("stoqserver.lib.restful.BaseResource.ensure_printer")
def test_check_drawer(mock_ensure_printer, error, current_station, store):
    mock_ensure_printer.side_effect = error

    assert check_drawer(store) is None
