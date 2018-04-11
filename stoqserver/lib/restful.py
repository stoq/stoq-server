# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2018 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or
## modify it under the terms of the GNU Lesser General Public License
## as published by the Free Software Foundation; either version 2
## of the License, or (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import contextlib
import datetime
import decimal
import functools
import logging
import os
import pickle
import uuid
from base64 import b64encode
from hashlib import md5

from kiwi.component import provide_utility, remove_utility
from kiwi.currency import currency
from flask import Flask, request, session, abort
from flask_restful import Api, Resource

from stoqlib.api import api
from stoqlib.database.runtime import set_current_branch_station
from stoqlib.database.interfaces import ICurrentUser
from stoqlib.domain.events import SaleConfirmedRemoteEvent
from stoqlib.domain.image import Image
from stoqlib.domain.payment.group import PaymentGroup
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.card import CreditCardData
from stoqlib.domain.payment.payment import Payment
from stoqlib.domain.person import LoginUser, Person
from stoqlib.domain.product import Product
from stoqlib.domain.sale import Sale
from stoqlib.domain.sellable import (Sellable, SellableCategory,
                                     ClientCategoryPrice)
from stoqlib.exceptions import LoginError
from stoqlib.lib.osutils import get_application_dir
from stoqlib.lib.dateutils import (INTERVALTYPE_MONTH, create_date_interval,
                                   localnow)
from stoqlib.lib.formatters import raw_document
from storm.expr import Desc, LeftJoin

_last_gc = None
_expire_time = datetime.timedelta(days=1)
_session = None
log = logging.getLogger(__name__)


def _get_user_hash():
    return md5(
        api.sysparam.get_string('USER_HASH').encode('UTF-8')).hexdigest()


@contextlib.contextmanager
def _get_session():
    global _session
    global _last_gc

    # Indexing some session data by the USER_HASH will help to avoid
    # maintaining sessions between two different databases. This could lead to
    # some errors in the POS in which the user making the sale does not exist.
    session_file = os.path.join(
        get_application_dir(), 'session-{}.db'.format(_get_user_hash()))
    if os.path.exists(session_file):
        with open(session_file, 'rb') as f:
            try:
                _session = pickle.load(f)
            except Exception:
                _session = {}
    else:
        _session = {}

    # From time to time remove old entries from the session dict
    now = localnow()
    if now - (_last_gc or datetime.datetime.min) > _expire_time:
        for k, v in list(_session.items()):
            if now - v['date'] > _expire_time:
                del _session[k]
        _last_gc = localnow()

    yield _session

    with open(session_file, 'wb') as f:
        pickle.dump(_session, f)


def _login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        session_id = request.headers.get('stoq-session', None)
        if session_id is None:
            abort(401, 'No session id provided in header')

        with _get_session() as s:
            session_data = s.get(session_id, None)
            if session_data is None:
                abort(401, 'Session does not exist')

            if localnow() - session_data['date'] > _expire_time:
                abort(401, 'Session expired')

            # Refresh last date to avoid it expiring while being used
            session_data['date'] = localnow()
            session['user_id'] = session_data['user_id']

        return f(*args, **kwargs)

    return wrapper


class _BaseResource(Resource):

    routes = []

    def get_arg(self, attr, default=None):
        """Get the attr from querystring, form data or json"""
        if request.is_json:
            return request.get_json().get(attr, None)

        return request.form.get(attr, request.args.get(attr, default))

    def get_data(self):
        """Returns all data the POS needs to run

        This includes:

        - Which branch he is operating for
        - What categories does it have
            - What sellables those categories have
                - The stock amount for each sellable (if it controls stock)
        """
        retval = {}
        with api.new_store() as store:
            # Current branch data
            retval['branch'] = api.get_current_branch(store).id

            categories_root = retval.setdefault('categories', [])
            aux = {}

            # SellableCategory and Sellable/Product data
            for c in store.find(SellableCategory):
                if c.category_id is None:
                    parent_list = categories_root
                else:
                    parent_list = aux.setdefault(
                        c.category_id, {}).setdefault('children', [])

                c_dict = aux.setdefault(c.id, {})
                parent_list.append(c_dict)

                # Set/Update the data
                c_dict.update({
                    'id': c.id,
                    'description': c.description,
                })
                c_dict.setdefault('children', [])
                products_list = c_dict.setdefault('products', [])

                tables = [Sellable, LeftJoin(Product, Product.id == Sellable.id)]
                sellables = store.using(*tables).find(
                    Sellable, category=c).order_by('height', 'description')
                for s in sellables:
                    ccp = store.find(ClientCategoryPrice, sellable_id=s.id)
                    ccp_dict = {}
                    for item in ccp:
                        ccp_dict[item.category_id] = str(item.price)

                    image_cls = store.find(Image, sellable_id=s.id,
                                           is_main=True).one()
                    image = ('data:image/png;base64,' +
                             b64encode(image_cls.image).decode()) if image_cls else None
                    products_list.append({
                        'id': s.id,
                        'description': s.description,
                        'price': str(s.price),
                        'category_prices': ccp_dict,
                        'color': s.product.part_number,
                        'image': image,
                        'availability': (
                            s.product and s.product.storable and
                            {
                                si.branch.id: str(si.quantity)
                                for si in s.product.storable.get_stock_items()
                            }
                        )
                    })

                aux[c.id] = c_dict

            # PaymentMethod data
            payment_methods = retval.setdefault('payment_methods', [])
            for pm in PaymentMethod.get_active_methods(store):
                if not pm.selectable():
                    continue

                data = {'name': pm.method_name,
                        'max_installments': pm.max_installments}
                if pm.method_name == 'card':
                    data['card_types'] = [CreditCardData.TYPE_CREDIT,
                                          CreditCardData.TYPE_DEBIT]

                payment_methods.append(data)

        return retval


class PingResource(_BaseResource):
    """Ping RESTful resource."""

    routes = ['/ping']

    def get(self):
        return 'pong from stoqserver'


def format_cpf(document):
    return '%s.%s.%s-%s' % (document[0:3], document[3:6], document[6:9],
                            document[9:11])


class ClientResource(_BaseResource):
    """Client RESTful resource."""
    routes = ['/client']

    def post(self):
        data = request.get_json()

        with api.new_store() as store:
            # Extra precaution in case we ever send the cpf already formatted
            document = format_cpf(raw_document(data['doc']))

            person = Person.get_by_document(store, document)
            if not (person and person.client):
                return data

            birthdate = person.individual.birth_date if person.individual else None

            saleviews = person.client.get_client_sales().order_by(Desc('confirm_date'))
            last_items = {}
            for saleview in saleviews:
                for item in saleview.sale.get_items():
                    last_items[item.sellable_id] = item.sellable.description
                    # Just the last 3 products the client bought
                    if len(last_items) == 3:
                        break

            data['category'] = person.client.category_id
            data['last_items'] = last_items
            data['name'] = person.name
            data['birthdate'] = birthdate
        return data


class LoginResource(_BaseResource):
    """Login RESTful resource."""

    routes = ['/login']

    def post(self):
        username = self.get_arg('user')
        pw_hash = self.get_arg('pw_hash')

        with api.new_store() as store:
            try:
                user = LoginUser.authenticate(store, username, pw_hash, None)
            except LoginError as e:
                abort(403, str(e))

        with _get_session() as s:
            session_id = str(uuid.uuid1()).replace('-', '')
            s[session_id] = {
                'date': localnow(),
                'user_id': user.id
            }

        return session_id


class DataResource(_BaseResource):
    """All the data the POS needs RESTful resource."""

    routes = ['/data']
    method_decorators = [_login_required]

    def get(self):
        return self.get_data()


class SaleResource(_BaseResource):
    """Sellable category RESTful resource."""

    routes = ['/sale']
    method_decorators = [_login_required]

    def post(self):
        data = request.get_json()

        document = data.get('client_document', '')
        products = data['products']
        payments = data['payments']

        with api.new_store() as store:
            set_current_branch_station(store, station_name=None)
            user = store.get(LoginUser, session['user_id'])
            # StoqTransactionHistory will use the current user to set the
            # responsible for the stock change
            provide_utility(ICurrentUser, user, replace=True)

            if document:
                document = format_cpf(raw_document(document))
                person = Person.get_by_document(store, document)
                client = person and person.client
            else:
                # XXX: How to inform the document in this case
                client = None

            # Create the sale
            branch = api.get_current_branch(store)
            group = PaymentGroup(store=store)
            sale = Sale(
                store=store,
                branch=branch,
                salesperson=user.person.sales_person,
                client=client,
                group=group,
                open_date=localnow(),
                coupon_id=None,
            )

            try:
                # Add products
                for p in products:
                    sellable = store.get(Sellable, p['id'])
                    sale.add_sellable(sellable,
                                      price=currency(p['price']),
                                      quantity=decimal.Decimal(p['quantity']))

                # Add payments
                for p in payments:
                    method = PaymentMethod.get_by_name(store, p['method'])
                    installments = p.get('installments', 1) or 1

                    due_dates = list(create_date_interval(
                        INTERVALTYPE_MONTH,
                        interval=1,
                        start_date=localnow(),
                        count=installments))
                    p_list = method.create_payments(
                        Payment.TYPE_IN, group, branch,
                        currency(p['value']), due_dates)

                    if method == 'card':
                        for payment in p_list:
                            data = method.operation.get_card_data_by_payment(
                                payment)
                            data.card_type = payment['card_type']
                            data.installments = installments

                # Confirm the sale
                group.confirm()
                sale.order()
                sale.confirm()

                # Fiscal plugins will connect to this event and "do their job"
                # It's their responsibility to raise an exception in case of
                # any error, which will then trigger the abort bellow
                SaleConfirmedRemoteEvent.emit(sale, document)
            except Exception as e:
                store.retval = False
                abort(500, str(e))
            finally:
                remove_utility(ICurrentUser)

        # This will make sure we update any stock or price changes products may
        # have between sales
        return self.get_data()


def bootstrap_app():
    app = Flask(__name__)
    # Indexing some session data by the USER_HASH will help to avoid maintaining
    # sessions between two different databases. This could lead to some errors in
    # the POS in which the user making the sale does not exist.
    app.config['SECRET_KEY'] = _get_user_hash()
    flask_api = Api(app)

    for cls in _BaseResource.__subclasses__():
        flask_api.add_resource(cls, *cls.routes)

    return app


def run_flaskserver(port):
    app = bootstrap_app()

    @app.after_request
    def after_request(response):
        # Add all the CORS headers the POS needs to have its ajax requests
        # accepted by the browser
        origin = request.headers.get('origin')
        if not origin:
            origin = request.args.get('origin', request.form.get('origin', '*'))
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'stoq-session, Content-Type'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response

    app.run('0.0.0.0', port=port)
