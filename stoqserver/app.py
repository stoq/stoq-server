# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

#
# Copyright (C) 2019 Async Open Source <http://www.async.com.br>
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
# Author(s): Stoq Team <stoq-devel@async.com.br>
#

import functools
import hashlib
import json
import logging
import traceback

import gevent
from blinker import signal
from flask import Flask, Response, request
from flask_restful import Api
from gevent.pywsgi import WSGIServer
from raven.contrib.flask import Sentry
from werkzeug.serving import run_with_reloader

from stoqlib.api import api
from stoqlib.database.runtime import get_current_station
from stoqlib.lib.dateutils import localnow
from stoqlib.lib.environment import is_developer_mode
from stoqlib.lib.translation import dgettext

from stoqserver import sentry
from stoqserver.sentry import raven_client, sentry_report, SENTRY_URL
from stoqserver.utils import get_user_hash

logger = logging.getLogger(__name__)

_ = functools.partial(dgettext, 'stoqserver')

is_multiclient = False


def register_routes(flask_api):
    # FIXME here we are importing BaseResource from the restful module because we need all
    # BaseResource subclasses in the restful module to be processed so that the loop below can work.
    # This is just to maintain the behavior prior to b68e1fecb while we develop a proper solution
    from stoqserver.lib.restful import BaseResource

    for cls in BaseResource.__subclasses__():
        flask_api.add_resource(cls, *cls.routes)


def bootstrap_app():
    app = Flask(__name__)

    # Indexing some session data by the USER_HASH will help to avoid maintaining
    # sessions between two different databases. This could lead to some errors in
    # the POS in which the user making the sale does not exist.
    app.config['SECRET_KEY'] = get_user_hash()
    app.config['PROPAGATE_EXCEPTIONS'] = True
    flask_api = Api(app)

    register_routes(flask_api)

    signal('StoqTouchStartupEvent').send()

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        traceback_info = "\n".join(traceback.format_tb(e.__traceback__))
        traceback_hash = hashlib.sha1(traceback_info.encode('utf-8')).hexdigest()[:8]
        traceback_exception = traceback.format_exception_only(type(e), e)[-1]
        timestamp = localnow().strftime('%Y%m%d-%H%M%S')

        logger.exception('Unhandled Exception: {timestamp} {error} {traceback_hash}'.format(
            timestamp=timestamp, error=e, traceback_hash=traceback_hash))

        sentry_report(type(e), e, e.__traceback__, traceback_hash=traceback_hash)

        return Response(json.dumps({'error': _('bad request!'), 'timestamp': timestamp,
                                    'exception': traceback_exception,
                                    'traceback_hash': traceback_hash}),
                        500, mimetype='application/json')

    return app


def _gtk_main_loop():
    from gi.repository import Gtk
    while True:
        while Gtk.events_pending():
            Gtk.main_iteration()
        gevent.sleep(0.1)


def run_flaskserver(port, debug=False, multiclient=False):
    from stoqlib.lib.environment import configure_locale
    # Force pt_BR for now.
    configure_locale('pt_BR')

    global is_multiclient
    is_multiclient = multiclient

    from .workers import WORKERS
    # For now we're disabling workers when stoqserver is serving multiple clients (multiclient mode)
    # FIXME: a proper solution would be to modify the workflow so that the clients ask the server
    # about devices health, the till status, etc. instead of the other way around.
    if not is_multiclient:
        for function in WORKERS:
            gevent.spawn(function, get_current_station(api.get_default_store()))

    try:
        from stoqserver.lib import stacktracer
        stacktracer.start_trace("/tmp/trace-stoqserver-flask.txt", interval=5, auto=True)
    except ImportError:
        pass

    app = bootstrap_app()
    app.debug = debug
    if not is_developer_mode():
        sentry.raven_client = Sentry(app, dsn=SENTRY_URL, client=raven_client)

    @app.after_request
    def after_request(response):
        # Add all the CORS headers the POS needs to have its ajax requests
        # accepted by the browser
        origin = request.headers.get('origin')
        if not origin:
            origin = request.args.get('origin', request.form.get('origin', '*'))
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS, DELETE'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        return response

    from stoqserver.lib.restful import has_sat, has_nfe
    logger.info('Starting wsgi server (has_sat=%s, has_nfe=%s)', has_sat, has_nfe)
    http_server = WSGIServer(('0.0.0.0', port), app, spawn=gevent.spawn_raw, log=logger,
                             error_log=logger)

    if debug:
        gevent.spawn(_gtk_main_loop)

        @run_with_reloader
        def run_server():
            http_server.serve_forever()
        run_server()
    else:
        http_server.serve_forever()
