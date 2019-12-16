import pytest
from unittest import mock

from stoqserver.taskmanager import Worker


@pytest.fixture
def worker():
    return Worker()


@pytest.fixture
def test_task():
    test_task = mock.MagicMock()
    test_task.link_only = False
    test_task.name = 'test_task'
    return test_task


@pytest.fixture
def plugin_manager_mock(test_task):
    manager_mock = mock.Mock(installed_plugins_names=['test_plugin'])
    plugin_mock = mock.Mock(get_server_tasks=mock.Mock(return_value=[test_task]))
    manager_mock.get_plugin.return_value = plugin_mock
    return manager_mock


@mock.patch('stoqserver.taskmanager.set_default_store')
@mock.patch('stoqserver.taskmanager.get_default_store')
@mock.patch('stoqserver.taskmanager.TaskManager.run_task')
@mock.patch('stoqserver.taskmanager.get_plugin_manager')
def test_start_tasks_with_pos_task_on_pos_station(
    mock_get_plugin_manager, mock_run_task, mock_get_default_store, set_default_store_mock,
    test_task, worker, store, plugin_manager_mock,
):
    store.is_link_server = mock.Mock(return_value=False)
    mock_get_default_store.return_value = store
    mock_get_plugin_manager.return_value = plugin_manager_mock

    worker._start_tasks()

    task_was_run = False
    for args, kwargs in mock_run_task.call_args_list:
        task = args[0]
        if task.name == 'test_plugin_test_task':
            task_was_run = True

    assert task_was_run


@mock.patch('stoqserver.taskmanager.set_default_store')
@mock.patch('stoqserver.taskmanager.get_default_store')
@mock.patch('stoqserver.taskmanager.TaskManager.run_task')
@mock.patch('stoqserver.taskmanager.get_plugin_manager')
def test_start_tasks_with_pos_task_on_server_station(
    mock_get_plugin_manager, mock_run_task, mock_get_default_store, set_default_store_mock,
    test_task, worker, store, plugin_manager_mock,
):
    mock.patch.object(store, 'is_link', mock.Mock(return_value=True))
    mock_get_default_store.return_value = store
    mock_get_plugin_manager.return_value = plugin_manager_mock

    worker._start_tasks()

    for call in mock_run_task.call_args_list:
        args, kwargs = call
        assert test_task not in args


@mock.patch('stoqserver.taskmanager.set_default_store')
@mock.patch('stoqserver.taskmanager.get_default_store')
@mock.patch('stoqserver.taskmanager.TaskManager.run_task')
@mock.patch('stoqserver.taskmanager.get_plugin_manager')
def test_start_tasks_with_server_task_on_pos_station(
    mock_get_plugin_manager, mock_run_task, mock_get_default_store, set_default_store_mock,
    plugin_manager_mock, worker, store, test_task,
):
    mock.patch.object(store, 'is_link', mock.Mock(return_value=False))
    mock_get_default_store.return_value = store
    mock_get_plugin_manager.return_value = plugin_manager_mock

    worker._start_tasks()

    for call in mock_run_task.call_args_list:
        args, kwargs = call
        assert test_task not in args


@mock.patch('stoqserver.taskmanager.set_default_store')
@mock.patch('stoqserver.taskmanager.get_default_store')
@mock.patch('stoqserver.taskmanager.TaskManager.run_task')
@mock.patch('stoqserver.taskmanager.get_plugin_manager')
def test_start_tasks_with_server_task_on_server_station(
    mock_get_plugin_manager, mock_run_task, mock_get_default_store, set_default_store_mock,
    test_task, worker, store, plugin_manager_mock,
):
    mock.patch.object(store, 'is_link', mock.Mock(return_value=True))
    mock_get_default_store.return_value = store
    mock_get_plugin_manager.return_value = plugin_manager_mock

    worker._start_tasks()

    task_was_run = False
    for args, kwargs in mock_run_task.call_args_list:
        task = args[0]
        if task.name == 'test_plugin_test_task':
            task_was_run = True

    assert task_was_run
