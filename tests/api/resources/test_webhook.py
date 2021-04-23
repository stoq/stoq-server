from unittest import mock
import json
import pytest

from stoqserver.signals import WebhookEvent


@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    get_config_mock = mock.Mock()
    get_config_mock.return_value = mock.Mock()
    get_config_mock.return_value.has_section.return_value = True
    get_config_mock.return_value.get.return_value = 'mysecretaccesstoken'
    monkeypatch.setattr('stoqserver.api.resources.webhook.get_config', get_config_mock)


@pytest.mark.usefixtures('mock_new_store')
def test_post_webhook_without_listeners(client):
    client.auth_token = 'mysecretaccesstoken'
    response = client.post("/v1/webhooks/event")
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res is None


@pytest.mark.usefixtures('mock_new_store')
def test_post_webhook(client):
    def callback(sender):
        return {'response': True}

    WebhookEvent.connect(callback)

    client.auth_token = 'mysecretaccesstoken'
    response = client.post("/v1/webhooks/event")
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res == {'response': True}
