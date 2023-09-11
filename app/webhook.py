import requests
from ._version import __version__ as app_version


class Webhook:
    """Trigger webhook for sender notification"""

    def __init__(self, conf: object, logger: object, message: object):
        self.conf = conf
        self.logger = logger
        self.message = message

    def call(self) -> None:
        """Call webhook"""
        webhook_url = self.conf.get('WEBHOOK_URL')
        webhook_secret = self.conf.get('WEBHOOK_SECRET')
        if webhook_url is None or webhook_secret is None:
            raise ValueError('WEBHOOK_URL and WEBHOOK_SECRET must be configured')

        user_agent = f'policyd-rate-guard/{app_version}'
        headers = {
            'User-Agent': user_agent,
            'Accept': 'application/json',
            # 'Content-Type': 'application/json',  # not needed when using 'json' param
        }

        metadata = self.get_metadata()

        if '{token}' in webhook_url:
            # Variant 1) Simple token as query parameter
            token = self.get_simple_token(webhook_secret)
            formatted_webhook_url = webhook_url.format(**metadata, token=token)
        else:
            # Variant 2) JWT Token as Authorization header
            token = self.get_jwt_token(webhook_secret)
            headers['Authorization'] = f'Bearer {token}'
            formatted_webhook_url = webhook_url.format(**metadata)

        # Setting data with 'json' param instead of 'data' will also set Content-Type header to 'application/json'
        response = requests.post(formatted_webhook_url, headers=headers, json=metadata)

        if response.status_code == 200:
            self.logger.info(f'Webhook call successful: POST {webhook_url} (User-Agent: {user_agent})')
        else:
            self.logger.warning(f'Webhook call failed with status code: {response.status_code} {response.text}')

    def get_metadata(self) -> dict:
        """Get metadata for webhook"""
        return {
            # message data
            'msgid': self.message.msgid,
            'sender': self.message.sender,
            'client_address': self.message.client_address,
            'client_name': self.message.client_name,
            'rcpt_count': self.message.rcpt_count,
            'from_addr': self.message.from_addr,
            'to_addr': self.message.to_addr,
            'timestamp': self.message.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            # ratelimit data
            'quota': self.message.ratelimit.quota,
            'quota_reset': self.message.ratelimit.quota_reset,
            'used': self.message.ratelimit.rcpt_counter,
        }

    def get_simple_token(self, secret: str) -> str:
        """Build token"""
        import hashlib
        plaintext = f'{secret}{self.message.sender}'
        return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()

    def get_jwt_token(self, secret: str) -> str:
        """Build JWT token"""
        import jwt
        from datetime import datetime, timedelta, timezone
        payload = {
            'sub': self.message.sender,
            'exp': datetime.now(tz=timezone.utc) + timedelta(seconds=60)
        }
        return jwt.encode(payload, secret, algorithm='HS256')
