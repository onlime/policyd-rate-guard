![PolicydRateGuard logo](./docs/logo-dark.png#gh-dark-mode-only)
![PolicydRateGuard logo](./docs/logo-light.png#gh-light-mode-only)

# PolicydRateGuard

[![CI](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml)
[![E2E](https://github.com/onlime/policyd-rate-guard/actions/workflows/e2e.yml/badge.svg)](https://github.com/onlime/policyd-rate-guard/actions/workflows/e2e.yml)
[![Latest release](https://img.shields.io/github/v/release/onlime/policyd-rate-guard)](https://github.com/onlime/policyd-rate-guard/releases)

A slick sender rate limit policy daemon for Postfix, written in Python.

©2026 by [Onlime GmbH](https://www.onlime.ch/) – Your Swiss webhosting provider living the "no BS" philosophy!

## Features ✨

PolicydRateGuard is a Postfix policy daemon with only one purpose: limit senders (SASL users) by the number of messages and recipients they send per day.

- **Simple Postfix integration** with `check_policy_service` in `smtpd_data_restrictions`, where the recipient count is final.
- **Individual quotas per sender** (SASL username), persistent or only for the current period (`quota` vs. `quota_reset`, `quota_locked`).
- Limits the **number of recipients** (and messages) per period. The period is defined by the daily cleanup timer, which resets the counters.
- **Exact under concurrency:** each message is counted with one atomic database statement, so parallel connections of one sender can't slip past the quota.
- Keeps counting while a sender is over quota, so you see who keeps retrying, and keeps totals per sender.
- Stores details of every message (`msgid, sender, rcpt_count, blocked, from_addr, to_addr, client ip and hostname`) in the `messages` table, purged after `MESSAGE_RETENTION` days.
- **Detailed log lines** to a file, the journal and/or syslog (`LOG_MAIL`, so they end up in `mail.log`).
- **Webhook** when a sender reaches the quota (once per period), authenticated with a JWT, e.g. to notify the sender.
- **Fail-safe:** if the daemon or the database is unavailable, Postfix carries on (`default_action=DUNNO`, `FAIL_ACTION=DUNNO`). Requests that don't come from Postfix can't trigger that path.
- **Hardened:** dedicated system user, systemd sandboxing, socket activation, hash-pinned dependencies, no secrets in error reports.
- asyncio server with persistent connections, bounded database connection pool with timeouts.
- An Ansible Galaxy role [`onlime.policyd_rate_guard`](https://galaxy.ansible.com/onlime/policyd_rate_guard) for the installation on a Debian mail server.
- **Well maintained**: in production at [Onlime GmbH](https://www.onlime.ch/), a Swiss webhoster with a rock-solid mail server architecture.

## Requirements

- Debian 13 (trixie) or another Linux with **Python 3.13+** and systemd
- Postfix 3.x with SASL authentication (tested with Postfix 3.10)
- MySQL 8.4+ or MariaDB (tested with MySQL 8.4 and 9.7, MariaDB 12.3)

## Production install 🚀

> [!IMPORTANT]
> Use the **[Ansible Galaxy](https://galaxy.ansible.com/onlime/policyd_rate_guard) role [`onlime.policyd_rate_guard`](https://github.com/onlime/ansible-role-policyd-rate-guard)**. It does all of the following, including the upgrade from 0.x:
>
> ```bash
> $ ansible-galaxy role install onlime.policyd_rate_guard
> ```
>
> ```yaml
> - hosts: smtphosts
>   roles:
>     - role: onlime.policyd_rate_guard
>       policyd_mysql_pass: '{{ vault_policyd_mysql_pass }}'
> ```

### Manual setup

1. Database and users: one for the daemon (data only), one for the migrations (schema changes):

   ```sql
   CREATE DATABASE `policyd-rate-guard`;
   CREATE USER `policyd`@localhost IDENTIFIED BY '…';
   GRANT SELECT, INSERT, UPDATE, DELETE ON `policyd-rate-guard`.* TO `policyd`@localhost;
   CREATE USER `policyd-rate-guard`@localhost IDENTIFIED BY '…';
   GRANT ALL ON `policyd-rate-guard`.* TO `policyd-rate-guard`@localhost;
   ```

2. Code and dependencies, owned by root. Install a release tag, not `main`:

   ```bash
   $ useradd --system --no-create-home --shell /usr/sbin/nologin policyd-rate-guard
   $ git clone --branch v1.0.0 https://github.com/onlime/policyd-rate-guard.git /opt/policyd-rate-guard
   $ cd /opt/policyd-rate-guard
   $ python3 -m venv venv
   $ venv/bin/pip install --require-hashes --only-binary=:all: --no-deps -r requirements.txt
   $ echo /opt/policyd-rate-guard/src > "$(venv/bin/python -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/policyd-rate-guard.pth"
   ```

3. Configuration in `/etc/policyd-rate-guard/`, readable only by root and the service:

   ```bash
   $ install -d -m 0750 -o root -g policyd-rate-guard /etc/policyd-rate-guard
   $ install -m 0640 -o root -g policyd-rate-guard .env.example /etc/policyd-rate-guard/policyd-rate-guard.env
   $ install -m 0600 -o root -g root yoyo.ini.example /etc/policyd-rate-guard/yoyo.ini
   $ editor /etc/policyd-rate-guard/policyd-rate-guard.env /etc/policyd-rate-guard/yoyo.ini
   $ venv/bin/yoyo apply --config /etc/policyd-rate-guard/yoyo.ini
   $ POLICYD_ENV_FILE=/etc/policyd-rate-guard/policyd-rate-guard.env venv/bin/python -m policyd_rate_guard check
   ```

4. systemd units and log rotation:

   ```bash
   $ cp deployment/systemd/* /etc/systemd/system/
   $ cp deployment/logrotate.d/policyd-rate-guard /etc/logrotate.d/
   $ systemctl daemon-reload
   $ systemctl enable --now policyd-rate-guard.socket policyd-rate-guard.service policyd-rate-guard-cleanup.timer
   ```

The daemon gets its listening socket from systemd (`policyd-rate-guard.socket`, `127.0.0.1:10033` by default). The socket stays open while the service restarts, so Postfix's requests wait a moment instead of being answered with the `default_action`.

### Configure Postfix

Integrate PolicydRateGuard with [`check_policy_service`](https://www.postfix.org/postconf.5.html#check_policy_service) in [`smtpd_data_restrictions`](https://www.postfix.org/postconf.5.html#smtpd_data_restrictions) (or `smtpd_end_of_data_restrictions`): only there the recipient count is final. In any other stage the daemon answers `DUNNO` and logs a warning.

`/etc/postfix/main.cf`:

```
smtpd_data_restrictions =
        reject_unauth_pipelining,
        check_policy_service { inet:127.0.0.1:10033, timeout=10s, default_action=DUNNO },
        permit
```

- `default_action=DUNNO`: if the daemon is unavailable, Postfix accepts the mail as if the rule wasn't there. Monitor the daemon (service state, and Postfix's `problem talking to server` warnings in `mail.log`).
- `timeout=10s`: with socket activation the kernel accepts connections even while the service is down, so without a short timeout Postfix would wait 2 × 100 s per SMTP session before using the `default_action`.
- BDAT (CHUNKING) is covered: Postfix evaluates `smtpd_data_restrictions` for it as well.

> [!TIP]
> Any local user can connect to `127.0.0.1:10033`. To allow only Postfix, use a unix socket: in `policyd-rate-guard.socket`, use `ListenStream=/var/spool/postfix/private/policyd-rate-guard` with `SocketUser=postfix`, `SocketGroup=postfix`, `SocketMode=0600`, and in Postfix `check_policy_service { unix:private/policyd-rate-guard, timeout=10s, default_action=DUNNO }`.

```bash
$ systemctl reload postfix
```

> [!NOTE]
> Postfix sends the recipient address to the policy service only for messages with exactly one recipient. For messages with several recipients, `to_addr` stays empty; `Cc` and `Bcc` are never available to a policy service.

### Upgrading from 0.7.x

Use role v1.0.0, which does all of this. Manually:

1. Stop and disable the old service, which occupies port 10033: `systemctl disable --now policyd-rate-guard.service`.
2. Don't reuse the old checkout: 0.x deployments made it owned by `postfix`, so it must be considered untrusted. Move it aside, clone the release fresh as root and create a new venv (steps 2–4 above).
3. Move the configuration from `/opt/policyd-rate-guard/.env` to `/etc/policyd-rate-guard/policyd-rate-guard.env`, and `yoyo.ini` to `/etc/policyd-rate-guard/yoyo.ini` with an absolute `sources = /opt/policyd-rate-guard/database/migrations`. Delete the old files, they were world-readable: rotate the passwords and the webhook secret.
4. Replace `run.py`/`cleanup.py` in custom units or scripts with `python -m policyd_rate_guard serve` / `cleanup`.
5. Set `MESSAGE_RETENTION` if you haven't: 0.x kept all messages forever by default. The first cleanup purges the backlog in batches.

The database schema is unchanged.

## Configuration ⚙️

All settings are environment variables, usually from `/etc/policyd-rate-guard/policyd-rate-guard.env` (python-dotenv syntax). Another file can be given with `--env-file` or `POLICYD_ENV_FILE`; variables in the process environment take precedence. Invalid values stop the daemon at startup with a list of all errors; `python -m policyd_rate_guard check` validates the configuration and the database connection.

| Variable | Default | Description |
| --- | --- | --- |
| `DB_HOST`, `DB_PORT` | `localhost`, `3306` | Database server (TCP) |
| `DB_UNIX_SOCKET` | | Database unix socket, e.g. `/run/mysqld/mysqld.sock`; overrides host and port |
| `DB_USER`, `DB_PASSWORD`, `DB_DATABASE` | `policyd-rate-guard`, empty, `policyd-rate-guard` | Credentials and database name |
| `DB_POOL_MAXCONNECTIONS` | `10` | Database connections, also the number of requests processed in parallel |
| `DB_POOL_MINCACHED`, `DB_POOL_MAXCACHED`, `DB_POOL_MAXUSAGE` | `0`, `10`, `10000` | [DBUtils PooledDB](https://webwareforpython.github.io/DBUtils/main.html#pooleddb-pooled-db-1) tuning |
| `DB_CONNECT_TIMEOUT`, `DB_READ_TIMEOUT`, `DB_WRITE_TIMEOUT` | `5`, `10`, `10` | Seconds |
| `DB_LOCK_WAIT_TIMEOUT` | `5` | Seconds to wait for a locked row or table before answering `FAIL_ACTION` |
| `QUOTA` | `1000` | Default quota (recipients and messages per period) of new senders |
| `ACTION_TEXT_BLOCKED` | `Rate limit reached, retry later` | Text of the `DEFER_IF_PERMIT` answer for senders over quota |
| `FAIL_ACTION` | `DUNNO` | Answer on internal errors (e.g. database down): `DUNNO` (accept) or `DEFER_IF_PERMIT` |
| `SOCKET` | `127.0.0.1,10033` | Only without socket activation: `host,port` (IPv6 as `::1,10033`) or a unix socket path |
| `SOCKET_BACKLOG`, `MAX_CONNECTIONS`, `IDLE_TIMEOUT`, `MAX_REQUEST_SIZE` | `256`, `1024`, `330`, `65536` | Listen backlog, open connections, idle seconds (longer than Postfix's `smtpd_policy_service_max_idle`), bytes per request |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FILE` | | Log file, e.g. `/var/log/policyd-rate-guard/policyd-rate-guard.log` |
| `LOG_CONSOLE`, `SYSLOG` | `False` | Log to stderr (the journal under systemd) and/or syslog (`LOG_MAIL`). Without any of `LOG_FILE`, `LOG_CONSOLE`, `SYSLOG`, logs go to stderr. |
| `LOG_MSG_PREFIX` | `False` | Prefix log lines with file and function name (debugging) |
| `MESSAGE_RETENTION` | `0` | Days to keep rows in `messages`; `0` keeps them forever |
| `PURGE_BATCH_SIZE` | `10000` | Rows deleted per statement when purging |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | , `dev` | Error reporting to [Sentry](https://sentry.io/) |
| `WEBHOOK_ENABLED` | `False` | Call a webhook when a sender reaches the quota, see below |
| `WEBHOOK_URL`, `WEBHOOK_SECRET`, `WEBHOOK_USE_JWT` | | Webhook URL, shared secret (base64), JWT authentication |
| `WEBHOOK_ALLOW_HTTP` | `False` | Allow `http://` webhook URLs (local development only) |

The log line of each counted message has this format (scripts may rely on it):

```
2026-11-08 12:34:56,789 INFO 4XyZ1abc2: client=mail.example.net[192.0.2.10], helo=mail.example.net, sasl_method=PLAIN, sasl_username=user@example.com, from=user@example.com, to=rcpt@example.org, recipient_count=1, curr_count=12/1000, status=ACCEPTED
```

Blocked messages are logged at `WARNING` with `status=BLOCKED`, the one that reached the quota with `status=BLOCKED (QUOTA_LIMIT_REACHED)`.

### Configure the API webhook (optional)

PolicydRateGuard can call an external API when a sender reaches the quota, once per period (the first blocked message). The webhook is called after Postfix got its answer, with a 3 s connect and 10 s read timeout, so it can't delay mail. It POSTs a JSON object like this:

```json
{
    "msgid": "TEST1234567",
    "sender": "demo1@example.com",
    "client_address": "172.19.0.2",
    "client_name": "unknown",
    "rcpt_count": 10,
    "from_addr": "test-from@example.com",
    "to_addr": "test-to@example.com",
    "timestamp": "2026-11-08 12:34:56",
    "quota": 1000,
    "quota_reset": 1000,
    "used": 1005
}
```

```ini
WEBHOOK_ENABLED=True
WEBHOOK_USE_JWT=True
WEBHOOK_URL="https://example.com/api/policyd/{sender}"
WEBHOOK_SECRET="Wk9YZXliVlVtY2pQcFlFUm9KY1U1ZkFFaUpWTk1FU20="
```

Every key of the JSON object can be used as `{placeholder}` in `WEBHOOK_URL` (URL-encoded); unknown placeholders are rejected at startup. `WEBHOOK_URL` must use `https://`. Generate the shared secret (always base64 encoded) like this:

```python
>>> import base64, secrets
>>> base64.b64encode(secrets.token_bytes(32))
```

**JWT in the Authorization header (recommended):** with `WEBHOOK_USE_JWT=True` and no `{token}` placeholder, PolicydRateGuard sends `Authorization: Bearer <JWT>`, signed with HS256 and the base64-decoded secret, valid for 60 s:

```python
payload = {
    'sub': sender,  # subject, the same as "sender" in the JSON data
    'iss': 'policyd-rate-guard',  # issuer
    'iat': timestamp,  # issued at
    'nbf': timestamp,  # not before
    'exp': timestamp + timedelta(seconds=60),  # expiration time
}
```

Verify it with a JWT library, e.g. [`lcobucci/jwt`](https://github.com/lcobucci/jwt) in PHP (check signature, `iss`, `exp` and that `sub` matches the sender).

**Simple token (deprecated):** with `WEBHOOK_USE_JWT=False` and a `{token}` placeholder (`https://example.com/api/policyd/{sender}?token={token}`), the token is `sha256(secret + sender)`. It never changes and ends up in access logs, so anyone who sees it once can replay it. The daemon logs a warning at startup; switch to JWT.

> [!NOTE]
> For a webhook running on your development machine, use `http://host.docker.internal:8080/…` in `.env.docker` together with `WEBHOOK_ALLOW_HTTP=True`.

## Development 👩‍💻

You need [uv](https://docs.astral.sh/uv/) and Docker.

```bash
$ git clone https://github.com/onlime/policyd-rate-guard.git
$ cd policyd-rate-guard
$ uv sync
```

### Tests

```bash
# unit tests (database tests are skipped)
$ uv run pytest

# with a database: TEST_DATABASE_URL points to a server where a temporary database can be created
$ docker compose up -d --wait db
$ TEST_DATABASE_URL=mysql://root:test@127.0.0.1:13312 uv run pytest --cov

# end-to-end through a real Postfix (Debian 13) with SASL users test01..test03@example.com / Example1234
$ docker compose up -d --build --wait
$ E2E_SMTP_PORT=1587 E2E_DATABASE_URL=mysql://root:test@127.0.0.1:13312/policyd-rate-guard \
    E2E_WEBHOOK_URL=http://127.0.0.1:18080 uv run pytest tests/e2e
$ docker compose down
```

The compose stack is also handy to try things by hand: submission on `localhost:1587` (e.g. `swaks --server localhost:1587 --auth PLAIN --auth-user test01@example.com --auth-password Example1234 --to rcpt@example.org`), the daemon's log with `docker compose logs -f policyd`, recorded webhook calls on `http://localhost:18080/calls`.

### Linting and type checking

```bash
$ uv run ruff format .
$ uv run ruff check .
$ uv run mypy
```

### Running the daemon locally

```bash
$ docker compose up -d --wait db migrate
$ cp .env.example .env    # adjust: DB_HOST=127.0.0.1, DB_PORT=13312, DB_PASSWORD=Example1234, LOG_CONSOLE=True
$ uv run policyd-rate-guard --env-file .env serve
$ uv run policyd-rate-guard --env-file .env cleanup
```

### Dependencies

`uv.lock` pins all dependencies; `requirements.txt` is exported from it, with hashes, for production installs with pip. After changing dependencies:

```bash
$ uv lock --upgrade-package <name>
$ uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt
```

CI checks that both are in sync and runs pip-audit on them; Dependabot proposes updates weekly.

### Database migrations

Migrations are managed with [yoyo](https://ollycope.com/software/yoyo/latest/) in `database/migrations`. Never rename existing migrations, yoyo tracks them by name. Other tools read the tables directly (e.g. an admin UI changing quotas), so keep schema changes backwards compatible.

```bash
$ cp yoyo.ini.docker yoyo.ini
$ uv run yoyo new --sql -m 'update table ratelimits'
$ uv run yoyo apply
```

### Releasing

Update `__version__` in `src/policyd_rate_guard/__init__.py` and `CHANGELOG.md`, then push a tag `vX.Y.Z`. The release workflow builds the packages, attests their provenance and creates the GitHub release with the changelog section.

## Credits 🙏

**[PolicydRateGuard](https://github.com/onlime/policyd-rate-guard)** is the official successor of [ratelimit-policyd](https://github.com/onlime/ratelimit-policyd), which ran rock-solid for 10 years, written in Perl.

It was greatly inspired by [policyd-rate-limit](https://github.com/nitmir/policyd-rate-limit) (by [@nitmir](https://github.com/nitmir)).

## Authors

Made with ❤️ by [Martin Wittwer (Wittwer IT Services)](https://www.wittwer-it.ch/) and [Philip Iezzi (Onlime GmbH)](https://www.onlime.ch/).

## License

This package is licensed under the [GPL-3.0 license](LICENSE); contributions are welcome. Please report security issues as described in [SECURITY.md](SECURITY.md).
