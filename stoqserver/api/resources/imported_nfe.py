# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2021 Stoq Tecnologia <http://www.stoq.com.br>
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

from flask import abort, jsonify, make_response
from storm.expr import And, Cast, Desc, Eq, Join

from stoqlib.lib.formatters import format_cnpj, raw_document
from stoqlib.lib.validators import validate_cnpj
from stoqlib.domain.person import Branch, Company, Person, UserBranchAccess

from stoqserver.lib.baseresource import BaseResource
from stoqserver.api.decorators import login_required, store_provider

log = logging.getLogger(__name__)

MAX_PAGE_SIZE = 100
NFEPROC_TYPE = '<nfeProc'


class ImportedNfeResource(BaseResource):
    method_decorators = [login_required, store_provider]
    routes = ['/api/v1/imported_nfe']

    def get(self, store):
        from stoqnfe.domain.distribution import ImportedNfe

        cnpj = self.get_arg('cnpj')
        limit = self.get_arg('limit')
        offset = self.get_arg('offset')

        if not cnpj:
            message = "'cnpj' not provided"
            log.error(message)
            abort(400, message)

        if not validate_cnpj(cnpj):
            message = "Invalid 'cnpj' provided"
            log.error(message)
            abort(400, message)

        if limit is not None:
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                message = "'limit' must be a number"
                log.error(message)
                abort(400, message)

            if limit > MAX_PAGE_SIZE:
                message = "'limit' must be lower than %s" % MAX_PAGE_SIZE
                log.error(message)
                abort(400, message)

        if offset is not None:
            try:
                offset = int(offset)
            except (TypeError, ValueError):
                message = "'offset' must be a number"
                log.error(message)
                abort(400, message)

        cnpj = format_cnpj(raw_document(cnpj))
        limit = limit or 20
        offset = offset or 0

        login_user = self.get_current_user(store)
        tables = [Branch, Join(Person, Branch.person_id == Person.id),
                  Join(Company, Company.person_id == Person.id)]
        query = Eq(Company.cnpj, cnpj)
        branches = store.using(*tables).find(Branch, query)

        # XXX There should exist at least one branch in database with
        # the cnpj from ImportedNfes. Otherwise, there is something wrong that
        # could lead to unwanted access to these ImportedNfes.
        assert branches

        for branch in branches:
            has_access = UserBranchAccess.has_access(store, login_user, branch)
            if has_access:
                continue

            message = 'login_user %s does not have access to branch %s' % \
                (login_user.id, branch.id)
            log.error(message)
            abort(403, message)

        query = And(ImportedNfe.cnpj == cnpj,
                    Cast(ImportedNfe.xml, 'text').startswith(NFEPROC_TYPE))
        result = store.find(ImportedNfe, query).order_by(Desc(ImportedNfe.te_id))
        result_count = result.count()
        imported_nfes = result.config(offset=offset, limit=limit)

        records = []
        for imported_nfe in imported_nfes:
            # FIXME: Change it to a store.find() when NFePurchase.key had been implemented
            query = "SELECT id FROM nfe_purchase WHERE cnpj='{}' AND xml::text ilike '%{}%'"
            nfe_purchase = store.execute(query.format(imported_nfe.cnpj,
                                                      imported_nfe.key)).get_one()

            process_date = imported_nfe.process_date
            record = {
                'id': imported_nfe.id,
                'key': imported_nfe.key,
                # Since process_date is a new column, we can't assure that
                # all entries have it fulfilled
                'process_date': process_date and process_date.isoformat(),
                'purchase_invoice_id': nfe_purchase and nfe_purchase[0]
            }
            records.append(record)

        next_offset = offset + limit
        has_next = result_count > next_offset
        next_ = None
        if has_next:
            next_ = self.routes[0] + '?limit={}&offset={}&cnpj={}'.format(
                limit, offset + limit, cnpj)

        has_previous = offset > 0
        previous = None
        if has_previous:
            previous = self.routes[0] + '?limit={}&offset={}&cnpj={}'.format(
                limit, max(offset - limit, 0), cnpj)

        response = {
            'previous': previous,
            'next': next_,
            'count': len(records),
            'total_records': result_count,
            'records': records
        }
        return make_response(jsonify(response), 200)
