import logging

from decimal import Decimal, DecimalException
from flask import abort, make_response, jsonify

from stoqlib.api import api
from stoqlib.domain.overrides import SellableBranchOverride
from stoqlib.domain.person import Branch
from stoqlib.domain.sellable import Sellable

from stoqserver.lib.baseresource import BaseResource

from stoqserver.api.decorators import login_required

log = logging.getLogger(__name__)


class SellableResource(BaseResource):
    method_decorators = [login_required]
    routes = ['/sellable/<uuid:sellable_id>/override/<uuid:branch_id>']

    def put(self, sellable_id, branch_id):
        with api.new_store() as store:
            data = self.get_json()
            status = data.get('status')
            try:
                base_price = Decimal(data.get('base_price', 0))
            except (ValueError, DecimalException):
                message = 'Price with incorrect format'
                log.error(message)
                abort(400, message)

            if status and status not in [Sellable.STATUS_AVAILABLE, Sellable.STATUS_CLOSED]:
                message = 'Status must be: {} or {}'.format(Sellable.STATUS_AVAILABLE,
                                                            Sellable.STATUS_CLOSED)
                log.error(message)
                abort(400, message)

            if base_price and base_price < 0:
                message = 'Price must be greater than 0'
                log.error(message)
                abort(400, message)

            sellable = store.get(Sellable, sellable_id)
            if not sellable:
                message = 'Sellable with ID = {} not found'.format(sellable_id)
                log.error(message)
                abort(404, message)

            branch = store.get(Branch, branch_id)
            if not branch:
                message = 'Branch with ID = {} not found'.format(branch_id)
                log.error(message)
                abort(404, message)

            sbo = SellableBranchOverride.find_by_sellable(branch=branch, sellable=sellable)
            if not sbo:
                sbo = SellableBranchOverride(store=store,
                                             branch=branch,
                                             sellable=sellable)
            sbo.status = status or sbo.status or Sellable.STATUS_AVAILABLE
            sbo.base_price = base_price or sbo.base_price

            return make_response(jsonify({
                'message': 'Product updated',
                'data': {
                    'sellable_id': sellable_id,
                    'base_price': str(sbo.base_price),
                    'status': sbo.status,
                    'branch_id': branch_id
                }
            }), 200)
