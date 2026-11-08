"""Test helpers."""


def postfix_request(
    sasl_username: str | None = 'user@example.com',
    *,
    protocol_state: str = 'DATA',
    recipient_count: int | str = 1,
    queue_id: str = '4XyZ1abc2',
    sender: str = 'from@example.com',
    recipient: str = 'rcpt@example.org',
    helo_name: str = 'client.example.net',
    client_name: str = 'client.example.net',
    client_address: str = '192.0.2.10',
    request: str = 'smtpd_access_policy',
) -> bytes:
    """A request in Postfix's attribute order (sasl_username comes after the client-controlled values)."""
    attrs = [
        ('request', request),
        ('protocol_state', protocol_state),
        ('protocol_name', 'ESMTP'),
        ('helo_name', helo_name),
        ('queue_id', queue_id),
        ('sender', sender),
        ('recipient', recipient),
        ('recipient_count', str(recipient_count)),
        ('client_address', client_address),
        ('client_name', client_name),
        ('reverse_client_name', client_name),
        ('instance', '1a2b.3c4d.5e6f.0'),
        ('sasl_method', 'PLAIN' if sasl_username else ''),
        ('sasl_username', sasl_username or ''),
        ('sasl_sender', ''),
        ('size', '1234'),
        ('ccert_subject', ''),
        ('encryption_protocol', 'TLSv1.3'),
        ('client_port', '54321'),
        ('policy_context', ''),
        ('server_address', '192.0.2.1'),
        ('server_port', '587'),
        ('compatibility_level', '3.10'),
        ('mail_version', '3.10.5'),
    ]
    return ''.join(f'{key}={value}\n' for key, value in attrs).encode() + b'\n'
