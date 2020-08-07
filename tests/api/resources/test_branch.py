import json
import pytest


@pytest.mark.usefixtures('mock_new_store')
def test_get_branch(client):
    response = client.get("/branch")
    res = json.loads(response.data.decode('utf-8'))

    assert "data" in res
    assert "acronym" in res["data"][0]
    assert "crt" in res["data"][0]
    assert "id" in res["data"][0]
    assert "is_active" in res["data"][0]
    assert "name" in res["data"][0]
