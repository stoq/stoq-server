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

import base64
import contextlib
import datetime
import decimal
import functools
import json
import logging
import os
import pickle
from queue import Queue
from threading import Event
import uuid
import io
import time
from hashlib import md5

from kiwi.component import provide_utility, remove_utility
from kiwi.currency import currency
from flask import Flask, request, session, abort, send_file, make_response, Response
from flask_restful import Api, Resource

from stoqlib.api import api
from stoqlib.database.runtime import set_current_branch_station, get_current_station
from stoqlib.database.interfaces import ICurrentUser
from stoqlib.domain.devices import DeviceSettings
from stoqlib.domain.events import SaleConfirmedRemoteEvent
from stoqlib.domain.image import Image
from stoqlib.domain.payment.group import PaymentGroup
from stoqlib.domain.payment.method import PaymentMethod
from stoqlib.domain.payment.card import CreditCardData, CreditProvider, CardPaymentDevice
from stoqlib.domain.payment.payment import Payment
from stoqlib.domain.person import LoginUser, Person
from stoqlib.domain.product import Product
from stoqlib.domain.sale import Sale
from stoqlib.domain.sellable import (Sellable, SellableCategory,
                                     ClientCategoryPrice)
from stoqlib.domain.till import Till, TillSummary
from stoqlib.exceptions import LoginError
from stoqlib.lib.configparser import get_config
from stoqlib.lib.dateutils import (INTERVALTYPE_MONTH, create_date_interval,
                                   localnow)
from stoqlib.lib.formatters import raw_document
from stoqlib.lib.osutils import get_application_dir
from stoqlib.lib.translation import stoqlib_gettext
from stoqlib.lib.threadutils import threadit
from storm.expr import Desc, LeftJoin


_ = stoqlib_gettext

try:
    from stoqntk.ntkapi import Ntk, NtkException, PwInfo, PwCnf
    # The ntk lib instance.
    has_ntk = True
except ImportError:
    has_ntk = False
    ntk = None

_last_gc = None
_expire_time = datetime.timedelta(days=1)
_session = None
log = logging.getLogger(__name__)

TRANSPARENT_PIXEL = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='  # nopep8


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
        # This is not working on all versions.
        #if request.is_json:
        if request.get_json():
            return request.get_json().get(attr, None)

        return request.form.get(attr, request.args.get(attr, default))

    def get_data(self):
        """Returns all data the POS needs to run

        This includes:

        - Which branch he is operating for
        - What categories does it have
            - What sellables those categories have
                - The stock amount for each sellable (if it controls stock)

        # FIXME: This does not need to be a method. Could be a function
        """
        retval = {}
        with api.new_store() as store:
            # Current station
            station = get_current_station(store)
            if station:
                retval['branch_station'] = station.name

            # Current user
            user = store.get(LoginUser, session['user_id'])
            retval['user'] = user.username

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

                    products_list.append({
                        'id': s.id,
                        'description': s.description,
                        'price': str(s.price),
                        'order': str(s.product.height),
                        'category_prices': ccp_dict,
                        'color': s.product.part_number,
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


class PrinterException(Exception):
    pass


class DrawerResource(_BaseResource):
    """Drawer RESTful resource."""

    routes = ['/drawer']
    method_decorators = [_login_required]

    @classmethod
    def _open_drawer(cls):
        if not api.device_manager.printer:
            raise PrinterException('Printer not configured in this station')
        api.device_manager.printer.open_drawer()

    @classmethod
    def _is_open(cls):
        if not api.device_manager.printer:
            return False
        return api.device_manager.printer.is_drawer_open()

    @classmethod
    def check_drawer_loop(cls):
        is_open = cls._is_open()

        # Check every second if it is opened.
        # Alert only if changes.
        while True:
            if not is_open and cls._is_open():
                is_open = True
                EventStream.put({
                    'type': 'DRAWER_ALERT_OPEN',
                })
            elif is_open and not cls._is_open():
                is_open = False
                EventStream.put({
                    'type': 'DRAWER_ALERT_CLOSE',
                })
            time.sleep(1)

    def get(self):
        """Get the current status of the drawer"""
        return self._is_open()

    def post(self):
        """Send a signal to open the drawer"""
        try:
            self._open_drawer()
        except Exception as e:
            raise PrinterException('Could not proceed with the operation. Reason: ' + str(e))
        return 'success', 200


class PingResource(_BaseResource):
    """Ping RESTful resource."""

    routes = ['/ping']

    def get(self):
        return 'pong from stoqserver'


def format_cpf(document):
    return '%s.%s.%s-%s' % (document[0:3], document[3:6], document[6:9],
                            document[9:11])


class TillResource(_BaseResource):
    """Till RESTful resource."""
    routes = ['/till']
    method_decorators = [_login_required]

    def _open_till(self, store, initial_cash_amount=0):
        station = get_current_station(store)
        last_till = Till.get_last(store)
        if not last_till or last_till.status == Till.STATUS_CLOSED:
            # Create till and open
            till = Till(store=store, station=station)
            till.open_till()
            till.initial_cash_amount = decimal.Decimal(initial_cash_amount)
        else:
            # Error, till already opened
            assert False

    def _close_till(self, store, till_summaries):
        # Here till object must exist
        till = Till.get_last(store)

        try:
            # Create TillSummaries
            till.get_day_summary()

            # Find TillSummary and store the user_value
            for till_summary in till_summaries:
                method = PaymentMethod.get_by_name(store, till_summary['method'])

                if till_summary['provider']:
                    provider = store.find(CreditProvider, short_name=till_summary['provider']).one()
                    summary = TillSummary.get_or_create(store, till=till, method=method.id,
                                                        provider=provider.id,
                                                        card_type=till_summary['card_type'])
                # Money method has no card_data or provider
                else:
                    summary = TillSummary.get_or_create(store, till=till, method=method.id)

                summary.user_value = decimal.Decimal(till_summary['user_value'])

            till.close_till()
        except Exception:
            # Log something ?
            store.rollback(close=False)

    def _add_credit_or_debit_entry(self, store, data):
        # Here till object must exist
        till = Till.get_last(store)
        user = store.get(LoginUser, session['user_id'])

        if data['operation'] == 'debit_entry':
            reason = _('The user %s removed cash from till') % user.username
            till.add_debit_entry(decimal.Decimal(data['entry_value']), reason)
        elif data['operation'] == 'credit_entry':
            reason = _('The user %s supplied cash to the till') % user.username
            till.add_credit_entry(decimal.Decimal(data['entry_value']), reason)

    def _get_till_summary(self, store, till):

        payment_data = []
        for summary in till.get_day_summary():
            payment_data.append({
                'method': summary.method.method_name,
                'provider': summary.provider.short_name if summary.provider else None,
                'card_type': summary.card_type,
            })

        # XXX: We shouldn't create TIllSummaries since we are not closing the Till,
        # so we must rollback.
        store.rollback(close=False)

        return payment_data

    def post(self):
        data = request.get_json()
        with api.new_store() as store:
            set_current_branch_station(store, station_name=None)
            # Provide responsible
            if data['operation'] == 'open_till':
                self._open_till(store, data['initial_cash_amount'])
            elif data['operation'] == 'close_till':
                self._close_till(store, data['till_summaries'])
            elif data['operation'] in ['debit_entry', 'credit_entry']:
                self._add_credit_or_debit_entry(store, data)

        return 200

    def get(self):
        # Retrieve Till data
        with api.new_store() as store:
            set_current_branch_station(store, station_name=None)
            till = Till.get_last(store)

            if not till:
                return None

            till_data = {
                'status': till.status,
                'opening_date': till.opening_date.strftime('%Y-%m-%d'),
                'closing_date': (till.closing_date.strftime('%Y-%m-%d') if
                                 till.closing_date else None),
                'initial_cash_amount': str(till.initial_cash_amount),
                'final_cash_amount': str(till.final_cash_amount),
                # Get payments data that will be used on 'close_till' action.
                'entry_types': self._get_till_summary(store, till),
            }

        return till_data


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


class EventStream(_BaseResource):
    """A stream of events from this server to the application.

    Callsites can use EventStream.put(event) to send a message from the server to the client
    asynchronously.

    Note that there should be only one client connected at a time. If more than one are connected,
    all of them will receive all events
    """
    _streams = []

    routes = ['/stream']

    @classmethod
    def put(cls, data):
        # Put event in all streams
        for stream in cls._streams:
            stream.put(data)

    def _loop(self, stream):
        while True:
            data = stream.get()
            yield "data: " + json.dumps(data) + "\n\n"

    def get(self):
        stream = Queue()
        self._streams.append(stream)

        # If we dont put one event, the event stream does not seem to get stabilished in the browser
        stream.put(json.dumps({}))
        return Response(self._loop(stream), mimetype="text/event-stream")


class TefResource(_BaseResource):
    routes = ['/tef']
    method_decorators = [_login_required]

    pending_transaction = None

    waiting_reply = Event()
    reply = Queue()

    NTK_MODES = {
        'credit': Ntk.TYPE_CREDIT,
        'debit': Ntk.TYPE_DEBIT,
        'voucher': Ntk.TYPE_VOUCHER,
    }

    def _setup_printer(self, store):
        if getattr(self, 'printer', None):
            return self.printer

        self.printer = None
        station = api.get_current_station(store)
        device = DeviceSettings.get_by_station_and_type(
            store, station, DeviceSettings.NON_FISCAL_PRINTER_DEVICE)

        if not device:
            return

        self.printer = device.get_interface()

    def _print_callback(self, full, holder, merchant, short):
        #print('print', len(full or ''), len(holder or ''), len(merchant or ''), len(short or ''))
        with api.new_store() as store:
            self._setup_printer(store)

        if holder and merchant:
            self.printer.print_line(holder)
            self.printer.cut_paper()
            self.printer.print_line(merchant)
        elif full:
            self.printer.print_line(full)
            self.printer.cut_paper()

    def _message_callback(self, message):
        EventStream.put({
            'type': 'TEF_DISPLAY_MESSAGE',
            'message': message
        })

    def _question_callback(self, questions):
        self.waiting_reply.set()

        # Right now we support asking only one question at a time. This could be imporved
        info = questions[0]
        EventStream.put({
            'type': 'TEF_ASK_QUESTION',
            'data': info.get_dict()
        })

        reply = self.reply.get()
        self.waiting_reply.clear()

        kwargs = {
            info.identificador.name: reply
        }
        ntk.add_params(**kwargs)
        return True

    def post(self):
        if not ntk:
            return

        if TefResource.pending_transaction:
            # There is a pending transaction, but the user just tried to add another tef payment. We
            # should confirm this one, otherwise a pending transaction error will be raised
            ntk.confirm_transaction(PwCnf.CNF_AUTO, TefResource.pending_transaction)

        data = request.get_json()
        if self.waiting_reply.is_set() and data['operation'] == 'reply':
            # There is already an operation happening, but its waiting for a user reply.
            # This is the reply
            self.reply.put(data['value'])
            return

        ntk.set_message_callback(self._message_callback)
        ntk.set_question_callback(self._question_callback)
        ntk.set_print_callback(self._print_callback)

        try:
            # This operation will be blocked here until its complete, but since we are running each
            # request using threads, the server will still be available to handle other requests
            # (specially when handling comunication with the user through the callbacks above)
            if data['operation'] == 'sale':
                retval = ntk.sale(value=data['value'], card_type=self.NTK_MODES[data['mode']])
                TefResource.pending_transaction = retval
            elif data['operation'] == 'admin':
                # Admin operation does not leave pending transaction
                retval = ntk.admin()
        except NtkException:
            retval = False

        message = ntk.get_info(PwInfo.RESULTMSG)
        EventStream.put({
            'type': 'TEF_OPERATION_FINISHED',
            'success': retval,
            'message': message,
        })


class ImageResource(_BaseResource):
    """Image RESTful resource."""

    routes = ['/image/<id>']

    def get(self, id):
        is_main = bool(request.args.get('is_main', None))
        # FIXME: The images should store tags so they could be requested by that tag and
        # product_id. At the moment, we simply check if the image is main or not and
        # return the first one.
        with api.new_store() as store:
            image = store.find(Image, sellable_id=id, is_main=is_main).any()

            if image:
                return send_file(io.BytesIO(image.image), mimetype='image/png')
            else:
                response = make_response(base64.b64decode(TRANSPARENT_PIXEL))
                response.headers.set('Content-Type', 'image/jpeg')
                return response


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

    def _get_card_device(self, store, name):
        device = store.find(CardPaymentDevice, description=name).any()
        if not device:
            device = CardPaymentDevice(store=store, description=name)
        return device

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
                    method_name = p['method']
                    tef_data = p.get('tef_data', {})
                    if method_name == 'tef':
                        p['provider'] = tef_data['card_name']
                        method_name = 'card'

                    method = PaymentMethod.get_by_name(store, method_name)
                    installments = p.get('installments', 1) or 1

                    due_dates = list(create_date_interval(
                        INTERVALTYPE_MONTH,
                        interval=1,
                        start_date=localnow(),
                        count=installments))
                    p_list = method.create_payments(
                        Payment.TYPE_IN, group, branch,
                        currency(p['value']), due_dates)

                    if method.method_name == 'card':
                        for payment in p_list:
                            card_data = method.operation.get_card_data_by_payment(payment)

                            card_type = p['mode']
                            device = self._get_card_device(store, 'TEF')
                            provider = store.find(CreditProvider, short_name=p['provider']).one()

                            if tef_data:
                                card_data.nsu = int(tef_data['aut_loc_ref'])
                                card_data.auth = int(tef_data['aut_ext_ref'])
                            card_data.update_card_data(device, provider, card_type, installments)

                # Confirm the sale
                group.confirm()
                sale.order()

                till = Till.get_last(store)
                sale.confirm(till)

                # Fiscal plugins will connect to this event and "do their job"
                # It's their responsibility to raise an exception in case of
                # any error, which will then trigger the abort bellow
                SaleConfirmedRemoteEvent.emit(sale, document)
            except Exception as e:
                store.retval = False
                abort(500, str(e))
            finally:
                remove_utility(ICurrentUser)

            if TefResource.pending_transaction:
                # TODO: Implement endpoint to cancel pending transaction
                ntk.confirm_transaction(PwCnf.CNF_AUTO, TefResource.pending_transaction)

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

    if has_ntk:
        global ntk
        config = get_config()
        if config:
            config_dir = config.get_config_directory()
            tef_dir = os.path.join(config_dir, 'ntk')
        else:
            # Tests don't have a config set. Use the plugin path as tef_dir, since it also has the
            # library
            import stoqntk
            tef_dir = os.path.dirname(os.path.dirname(stoqntk.__file__))

        ntk = Ntk(os.path.join(tef_dir, 'PGWebLib.so'))
        ntk.init(tef_dir)

    return app


def run_flaskserver(port, debug=False):
    # Check drawer in a separated thread
    threadit(DrawerResource.check_drawer_loop)

    app = bootstrap_app()
    app.debug = debug

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

    app.run('0.0.0.0', port=port, debug=debug, threaded=True)
