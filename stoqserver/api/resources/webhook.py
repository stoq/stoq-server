import logging

from flask import make_response, request

from stoqlib.lib.configparser import get_config
from stoqserver.lib.baseresource import BaseResource
from stoqserver.signals import WebhookEvent

log = logging.getLogger(__name__)


class IntegrationWebhookException(Exception):
    pass


class WebhookEventResource(BaseResource):
    routes = ['/v1/webhooks/event']

    def check_token(self, token):
        config = get_config()
        if not config.has_section('Integration'):
            return False

        return token == config.get('Integration', 'access_token')

    def post(self):
        token = request.headers.get('Authorization')
        if not self.check_token(token):
            return make_response('Invalid access token', 401)

        data = self.get_json()
        log.info('Webhook event: %s', data)

        # An event can have multiple replies
        try:
            replies = [i[1] for i in WebhookEvent.send(data)]
        except IntegrationWebhookException as err:
            log.exception('Error')
            make_response(str(err), 500)

        # Get first non false response from the event
        reply = replies[0] if replies else None
        return reply, 200
