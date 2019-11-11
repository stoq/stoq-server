import sys
from unittest import mock

import pytest

import stoqserver
from stoqserver.sentry import SENTRY_URL, sentry_report, setup_excepthook, setup_sentry


class CustomException(Exception):
    pass


@mock.patch('stoqserver.sentry.stoqserver')
@mock.patch('stoqserver.sentry.raven_client', spec=('user_context', 'captureException'))
def test_sentry_report(raven_client_mock, stoqserver_mock):
    traceback = mock.Mock()
    stoqserver_mock.library.uninstalled = False

    sentry_report(CustomException, 69, traceback)

    assert raven_client_mock.user_context.call_count == 1
    assert raven_client_mock.captureException.call_count == 1


@mock.patch('stoqserver.sentry.stoqserver')
@mock.patch('stoqserver.sentry.raven_client', spec=('user_context', 'captureException'))
def test_sentry_report_without_user_context(raven_client_mock, stoqserver_mock):
    traceback = mock.Mock()
    stoqserver_mock.library.uninstalled = False
    del raven_client_mock.user_context

    sentry_report(CustomException, 69, traceback)

    assert raven_client_mock.captureException.call_count == 1


@mock.patch('stoqserver.sentry.stoqserver')
@mock.patch('stoqserver.sentry.raven_client', spec=('user_context', 'captureException'))
def test_sentry_report_developer_mode(raven_client_mock, stoqserver_mock):
    traceback = mock.Mock()
    stoqserver_mock.library.uninstalled = True

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
    sentry_client_mock.assert_called_once_with(SENTRY_URL, release=stoqserver.version_str)
    setup_excepthook_mock.assert_called_once_with()
