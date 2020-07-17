import json
import os
import tempfile

import pytest
from flask.testing import FlaskClient

from stoqlib.lib.decorators import cached_property
from stoqserver.app import bootstrap_app


class StoqTestClient(FlaskClient):
    @cached_property(ttl=0)
    def auth_token(self):
        response = super().post(
            '/login',
            data={
                'user': self.user.username,
                'pw_hash': self.user.pw_hash,
                'station_name': self.station.name
            })
        ans = json.loads(response.data.decode())
        return ans['token'].replace('JWT', 'Bearer')

    def _request(self, method_name, *args, **kwargs):
        method = getattr(super(), method_name)
        response = method(
            *args,
            headers={'Authorization': self.auth_token},
            content_type='application/json',
            **kwargs,
        )
        try:
            response.json = json.loads(response.data.decode())
        except AttributeError:
            pass
        return response

    def get(self, *args, **kwargs):
        return self._request('get', *args, **kwargs)

    def post(self, *args, **kwargs):
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs.pop('json'))
        return self._request('post', *args, **kwargs)

    def put(self, *args, **kwargs):
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs.pop('json'))
        return self._request('put', *args, **kwargs)


# This is flask test client according to boilerplate:
# https://flask.palletsprojects.com/en/1.0.x/testing/
@pytest.fixture
def client(current_user, current_station):
    app = bootstrap_app()
    db_fd, app.config['DATABASE'] = tempfile.mkstemp()
    app.config['TESTING'] = True
    app.test_client_class = StoqTestClient
    with app.test_client() as client:
        with app.app_context():
            client.user = current_user
            client.station = current_station
            yield client

    os.close(db_fd)
    os.unlink(app.config['DATABASE'])
