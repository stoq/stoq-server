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

from flask import make_response, jsonify

from stoqlib.domain.person import Branch

from stoqserver.lib.baseresource import BaseResource
from stoqserver.api.decorators import login_required, store_provider


class BranchResource(BaseResource):
    method_decorators = [login_required, store_provider]
    routes = ['/branch']

    def get(self, store):
        branches = []
        for branch in list(store.find(Branch)):
            branches.append({
                "id": branch.id,
                "name": branch.name,
                "acronym": branch.acronym,
                "is_active": branch.is_active,
                "crt": branch.crt
            })

        return make_response(jsonify({
            'data': branches
        }), 200)
