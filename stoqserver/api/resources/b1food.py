# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2020 Stoq Tecnologia <http://www.stoq.com.br>
# All rights reserved
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., or visit: http://www.gnu.org/.
#
# Author(s): Stoq Team <dev@stoq.com.br>
#

import logging

from flask import abort, make_response, jsonify, request

from stoqlib.lib.configparser import get_config

from stoqserver.api.decorators import b1food_login_required
from stoqserver.lib.baseresource import BaseResource

log = logging.getLogger(__name__)

global b1food_token


# just a random token untill we have a domain to persist this.
def generate_b1food_token(size=128):
    import string
    import random

    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(size))


b1food_token = generate_b1food_token()


class B1foodLoginResource(BaseResource):
    routes = ['/b1food/oauth/authenticate']

    def get(self):
        if 'client_id' not in request.args:
            abort(400, 'Missing client_id')
        client_id = request.args['client_id']

        config = get_config()
        config_client_id = config.get("B1Food", "client_id") or ""
        if client_id != config_client_id and config_client_id != "":
            log.error('Login failed for client_id %s', client_id)
            abort(403, 'Login failed for client_id {}'.format(client_id))

        return make_response(jsonify({
            'token_type': 'Bearer',
            'expires_in': float('inf'),
            'access_token': b1food_token
        }), 200)


class IncomeCenterResource(BaseResource):
    method_decorators = [b1food_login_required]
    routes = ['/b1food/centrosrenda']

    def get(self):
        return []
