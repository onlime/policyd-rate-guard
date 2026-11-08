import pytest

from policyd_rate_guard.protocol import clamp, format_response, parse_request, sanitize

from .helpers import postfix_request


def test_parse_postfix_request() -> None:
    request = parse_request(postfix_request('user@example.com', recipient_count=3))
    assert request.request_type == 'smtpd_access_policy'
    assert request.protocol_state == 'DATA'
    assert request.queue_id == '4XyZ1abc2'
    assert request.sasl_username == 'user@example.com'
    assert request.recipient_count(1000) == 3
    assert request.get('sender') == 'from@example.com'
    assert request.get('sasl_sender') is None  # empty values count as missing


def test_parse_skips_malformed_lines_and_keeps_equals_in_values() -> None:
    request = parse_request(b'request=smtpd_access_policy\nno equals sign\n=no name\nsender=a=b@example.com\r\n\n')
    assert dict(request.attributes) == {'request': 'smtpd_access_policy', 'sender': 'a=b@example.com'}


def test_invalid_utf8_is_replaced_not_fatal() -> None:
    request = parse_request(b'request=smtpd_access_policy\nhelo_name=\xff\xfe\nsasl_username=u@example.com\n\n')
    assert request.get('helo_name') == '��'
    assert request.sasl_username == 'u@example.com'


def test_long_client_controlled_values_do_not_hide_sasl_username() -> None:
    """0.x read only 2048 bytes, so padding MAIL FROM/HELO cut off sasl_username (and the limit)."""
    data = postfix_request('victim@example.com', sender='x' * 1900 + '@example.com', helo_name='h' * 250)
    assert data.index(b'sasl_username=') > 2048
    assert parse_request(data).sasl_username == 'victim@example.com'


def test_recipient_count_validation() -> None:
    for raw, expected in [('0', 0), ('7', 7), ('100', 100), ('101', None), ('-1', None), ('1e3', None),
                          ('', None), ('٣', None), (' 3', None)]:  # fmt: skip
        request = parse_request(f'recipient_count={raw}\n'.encode())
        assert request.recipient_count(100) == expected, raw


def test_format_response() -> None:
    assert format_response('OK') == b'action=OK\n\n'
    assert format_response('DEFER_IF_PERMIT Rate limit\nreached') == b'action=DEFER_IF_PERMIT Rate limit reached\n\n'


def test_sanitize_and_clamp() -> None:
    assert sanitize('a\nb\rc\x00d\x7f') == 'a\\x0ab\\x0dc\\x00d\\x7f'
    assert sanitize('x' * 10, max_length=4) == 'xxxx…'
    assert sanitize(None) == 'None'
    assert clamp('abcdef', 3) == 'abc'
    assert clamp(None, 3) is None


@pytest.mark.parametrize(
    'data', [b'', b'\n\n', b'=\n==\n', b'no equals sign\n\n', b'\xff\xfe\x00=\x80\n\n', b'a=b=c\n' * 1000]
)
def test_parser_never_raises(data: bytes) -> None:
    request = parse_request(data)
    assert isinstance(dict(request.attributes), dict)
    request.recipient_count(1_000_000)


@pytest.mark.parametrize('action', ['OK', '', 'DEFER_IF_PERMIT a\nb', 'x\r\n\r\naction=OK', '\x00'])
def test_response_is_always_one_line(action: str) -> None:
    response = format_response(action)
    assert response.startswith(b'action=')
    assert response.endswith(b'\n\n')
    assert response.count(b'\n') == 2


def test_recipient_count_with_too_many_digits() -> None:
    """int() refuses more than 4300 digits: that must be an invalid value, not an exception."""
    request = parse_request(postfix_request('u@example.com', recipient_count='9' * 5000))
    assert request.recipient_count(1_000_000) is None


def test_sanitize_escapes_c1_controls_and_line_separators() -> None:
    """U+009B is an 8-bit CSI to some terminals; U+2028/2029 split a line for str.splitlines(). Postfix passes them on
    from an SMTPUTF8 MAIL FROM."""
    assert sanitize('a\x9b31m\x85b\u2028c\u2029d\x7f') == 'a\\x9b31m\\x85b\\u2028c\\u2029d\\x7f'
    assert sanitize('jörg@exämple.org') == 'jörg@exämple.org'
