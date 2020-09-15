import sys
from unittest import mock
from urllib.error import URLError

import pytest

import stoqserver
from stoqserver.sentry import (SENTRY_URL, sentry_report, setup_excepthook,
                               setup_sentry, SilentTransport)


class CustomException(Exception):
    pass


@mock.patch('stoqserver.sentry.importlib')
@mock.patch('stoqserver.sentry.raven_client', spec=('user_context', 'captureException'))
def test_sentry_report(raven_client_mock, importlib_mock):
    traceback = mock.Mock()
    importlib_mock.util.find_spec.return_value = True

    sentry_report(CustomException, 69, traceback)

    assert raven_client_mock.user_context.call_count == 1
    assert raven_client_mock.captureException.call_count == 1


@mock.patch('stoqserver.sentry.importlib')
@mock.patch('stoqserver.sentry.raven_client', spec=('user_context', 'captureException'))
def test_sentry_report_without_user_context(raven_client_mock, importlib_mock):
    traceback = mock.Mock()
    importlib_mock.util.find_spec.return_value = True
    del raven_client_mock.user_context

    sentry_report(CustomException, 69, traceback)

    assert raven_client_mock.captureException.call_count == 1


@mock.patch('stoqserver.sentry.importlib')
@mock.patch('stoqserver.sentry.raven_client', spec=('user_context', 'captureException'))
def test_sentry_report_developer_mode(raven_client_mock, importlib_mock):
    traceback = mock.Mock()
    importlib_mock.util.find_spec.return_value = False

    sentry_report(CustomException, 69, traceback)

    assert raven_client_mock.captureException.call_count == 0


@mock.patch('traceback.print_exception')
@mock.patch('stoqserver.sentry.sentry_report')
def test_setup_excepthook(sentry_report_mock, print_exception_mock):
    default_excepthook = sys.excepthook

    setup_excepthook()

    assert sys.excepthook is not default_excepthook
    assert sentry_report_mock.call_count == 0
    assert print_exception_mock.call_count == 0
    try:
        sys.excepthook(CustomException, CustomException(), mock.MagicMock())
    except TypeError as exc:
        pytest.fail('raised {!r}'.format(exc))
    assert sentry_report_mock.call_count == 1
    assert print_exception_mock.call_count == 1


@mock.patch('stoqserver.sentry.register_config')
@mock.patch('stoqserver.sentry.setup_excepthook')
@mock.patch('stoqserver.sentry.raven.Client')
def test_setup_sentry(sentry_client_mock, setup_excepthook_mock, register_config_mock):
    options_mock = mock.Mock(filename='')

    setup_sentry(options_mock)

    assert register_config_mock.call_count == 1
    sentry_client_mock.assert_called_once_with(SENTRY_URL, release=stoqserver.version_str,
                                               transport=SilentTransport)
    setup_excepthook_mock.assert_called_once_with()


def test_silent_transport_handle_fail():
    class CustomException(Exception):
        pass

    failure_cb = mock.Mock()
    exc = CustomException()

    result = SilentTransport._handle_fail(failure_cb, 'http://pudim.com.br', exc)

    assert result == failure_cb.return_value
    failure_cb.assert_called_once_with(exc)


def test_silent_transport_handle_fail_url_error():
    failure_cb = mock.Mock()
    exc = URLError('fodeu')

    result = SilentTransport._handle_fail(failure_cb, 'http://pudim.com.br', exc)

    assert result is None
    assert failure_cb.call_count == 0


@mock.patch('stoqserver.sentry.ThreadedHTTPTransport.send_sync')
def test_silent_transport_send_sync(super_send_sync_mock):
    transport = SilentTransport()
    url = 'http://pudim.com.br'
    data = {'foo': 'bar'}
    headers = {'cabeça de': 'alho'}
    success_cb = mock.Mock()
    failure_cb = mock.Mock()

    transport.send_sync(url, data, headers, success_cb, failure_cb)

    assert super_send_sync_mock.call_count == 1
    call = super_send_sync_mock.call_args_list[0][0]
    assert call[:4] == (url, data, headers, success_cb)
    handle_fail = call[4]
    assert handle_fail.func == transport._handle_fail
    assert handle_fail.args == (failure_cb, url)
