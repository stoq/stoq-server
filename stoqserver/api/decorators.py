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

import functools

from stoqlib.lib.component import provide_utility
from flask import abort, request

from stoqlib.api import api
from stoqlib.database.interfaces import ICurrentUser
from stoqlib.domain.person import LoginUser
from stoqlib.domain.token import AccessToken


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # token should be sent through a header using the format 'Bearer <token>'
        auth = request.headers.get('Authorization', '').split('Bearer ')
        if len(auth) != 2:
            abort(401)

        with api.new_store() as store:
            access_token = AccessToken.get_by_token(store=store, token=auth[1])
            if not access_token.is_valid():
                abort(403, "token {}".format(access_token.status))

            # FIXME: the user utility acts as a singleton and since we'd like to have stoqserver API
            # accepting requests from different stations (users), we cannot use this pattern as it
            # can lead to racing problems. For now we are willing to put a lock in every request,
            # but the final solution should be a refactor that makes every endpoint use the user
            # provided in the token payload instead of this 'global' one.
            user = store.get(LoginUser, access_token.payload['user_id'])
            provide_utility(ICurrentUser, user, replace=True)

        return f(*args, **kwargs)
    return wrapper


def store_provider(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        with api.new_store() as store:
            try:
                return f(store, *args, **kwargs)
            except Exception as e:
                store.retval = False
                raise e

    return wrapper
