import json
import pytest

from stoqserver.signals import WebhookEvent


@pytest.mark.usefixtures('mock_new_store')
def test_post_webhook_without_listeners(client):
    response = client.post("/v1/webhooks/event")
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res is None


@pytest.mark.usefixtures('mock_new_store')
def test_post_webhook(client):
    def callback(sender):
        return {'response': True}

    WebhookEvent.connect(callback)

    response = client.post("/v1/webhooks/event")
    res = json.loads(response.data.decode('utf-8'))
    assert response.status_code == 200
    assert res == {'response': True}
