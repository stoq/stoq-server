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
