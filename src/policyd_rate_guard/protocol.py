"""Postfix policy delegation protocol (https://www.postfix.org/SMTPD_POLICY_README.html).

A request is a list of ``name=value`` lines terminated by an empty line. Parsing never raises: malformed lines
are skipped and invalid bytes are replaced, so attacker-controlled values (HELO, MAIL FROM, client names) can't
push a request into an error path.
"""

from dataclasses import dataclass
from types import MappingProxyType

# Protocol states in which the recipient count is final (smtpd_data_restrictions, smtpd_end_of_data_restrictions).
# BDAT (CHUNKING) is reported as DATA, see https://www.postfix.org/BDAT_README.html
COUNTING_STATES = frozenset({'DATA', 'BDAT', 'END-OF-MESSAGE'})
# The other states in which Postfix may call a policy service, where the recipient count isn't final
POSTFIX_STATES = frozenset({'CONNECT', 'EHLO', 'HELO', 'MAIL', 'RCPT', 'VRFY', 'ETRN'})

# C0 and C1 control characters (U+009B is an 8-bit CSI to some terminals), and the line and paragraph separators
# that str.splitlines() splits on
_CONTROL_CHARS = {i: f'\\x{i:02x}' for i in (*range(0x20), *range(0x7F, 0xA0))} | {
    i: f'\\u{i:04x}' for i in (0x2028, 0x2029)
}


def sanitize(value: object, max_length: int = 1024) -> str:
    """Make a value safe for a single log line: escape control characters, cap the length."""
    text = str(value).translate(_CONTROL_CHARS)
    return text if len(text) <= max_length else text[:max_length] + '…'


def clamp(value: str | None, max_length: int) -> str | None:
    """Fit a value into a VARCHAR(n) column, so strict and non-strict sql_mode behave the same."""
    if value is None:
        return None
    return value[:max_length]


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    attributes: MappingProxyType[str, str]

    def get(self, name: str) -> str | None:
        """Attribute value, or None if missing or empty (Postfix sends empty values for unknown data)."""
        return self.attributes.get(name) or None

    @property
    def request_type(self) -> str | None:
        return self.get('request')

    @property
    def protocol_state(self) -> str | None:
        return self.get('protocol_state')

    @property
    def queue_id(self) -> str | None:
        return self.get('queue_id')

    @property
    def sasl_username(self) -> str | None:
        return self.get('sasl_username')

    def recipient_count(self, maximum: int) -> int | None:
        """The recipient count, or None if missing or not a plausible value."""
        raw = self.get('recipient_count')
        if raw is None or not raw.isascii() or not raw.isdigit() or len(raw) > len(str(maximum)):
            return None
        count = int(raw)
        return count if count <= maximum else None


def parse_request(data: bytes) -> PolicyRequest:
    """Parse one request (including or excluding the terminating empty line)."""
    attributes: dict[str, str] = {}
    for line in data.decode('utf-8', errors='replace').split('\n'):
        name, sep, value = line.rstrip('\r').partition('=')
        if sep and name:
            attributes[name] = value
    return PolicyRequest(MappingProxyType(attributes))


def format_response(action: str) -> bytes:
    """Encode a reply; the action text is forced onto one line."""
    single_line = ' '.join(action.split())
    return f'action={single_line}\n\n'.encode()
