![PolicydRateGuard logo](./docs/logo-dark.png#gh-dark-mode-only)
![PolicydRateGuard logo](./docs/logo-light.png#gh-light-mode-only)

# PolicydRateGuard

[![CI](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml)
[![E2E](https://github.com/onlime/policyd-rate-guard/actions/workflows/e2e.yml/badge.svg)](https://github.com/onlime/policyd-rate-guard/actions/workflows/e2e.yml)
[![Latest release](https://img.shields.io/github/v/release/onlime/policyd-rate-guard)](https://github.com/onlime/policyd-rate-guard/releases)

A slick sender rate limit policy daemon for Postfix, written in Python.

©2026 by [Onlime GmbH](https://www.onlime.ch/) – Your Swiss webhosting provider living the "no BS" philosophy!

## Features ✨

Actually, PolicydRateGuard is just a super simple Postfix policy daemon with only one purpose: limit senders (SASL users) by the number of messages and recipients they send.

But let me name some features that make it stand out from other solutions:

- **Super easy Postfix integration** using `check_policy_service` in `smtpd_data_restrictions`, where the recipient count is final.
- **Tuned for high performance:** an asyncio server with persistent Postfix connections, and a bounded [DBUtils PooledDB](https://webwareforpython.github.io/DBUtils/) connection pool with timeouts.
- **Exact under concurrency:** each message is counted with one atomic database statement, so parallel connections of one sender can't slip past the quota.
- Set **individual sender (SASL username) quotas**, which can be both persistent or only for the current time period (`quota`, `quota_reset`, `quota_locked`).
- Limit senders to **number of recipients** (and messages) per time period.
- Automatically fills the `ratelimits` table with new senders (SASL username) upon their first email sent.
- Set your own **time period (usually 24hrs)** by resetting the counters via the systemd cleanup timer (or a cronjob).
- Continues to raise counters (`msg_counter`, `rcpt_counter`) even in over quota state, so you know if a sender keeps retrying/spamming.
- Keeps **totals** of all messages/recipients sent for each sender.
- Stores **detailed information for all sent messages** (`msgid, sender, rcpt_count, blocked, from_addr, to_addr, client ip and hostname`) in the `messages` table, purged after `MESSAGE_RETENTION` days.
- **Logs detailed message information** to a file, the journal and/or syslog (`LOG_MAIL` facility, so the logs end up in `mail.log`).
- **Maximum failure safety:** if the daemon or the database is unavailable, Postfix carries on (`default_action=DUNNO`, `FAIL_ACTION=DUNNO`), so mail is never rejected because of PolicydRateGuard. Malformed requests are answered `DEFER_IF_PERMIT`, never `DUNNO`; to keep other local users away from the daemon, use a unix socket (see below).
- **Block action message** `"Rate limit reached, retry later"` can be configured.
- Lots of configuration params via a simple `.env` file, all validated at startup.
- **Secure setup:** a dedicated unprivileged system user, systemd sandboxing and socket activation, no secrets in error reports.
- **Supports external API webhooks**, authenticated with a JWT. The webhook is triggered when a sender reaches the quota for the first time in a period, so you can send out notifications through your own or any 3rd-party app.
- **Sentry** integration for exception reporting.
- A super slick minimal codebase with **only a few dependencies** ([PyMySQL](https://pypi.org/project/pymysql/), [DBUtils](https://webwareforpython.github.io/DBUtils/), [python-dotenv](https://pypi.org/project/python-dotenv/), [yoyo-migrations](https://pypi.org/project/yoyo-migrations/), plus requests, PyJWT and sentry-sdk), installed with plain `pip` in a virtual environment. PyMySQL is a pure-Python MySQL client library, so you won't have any trouble on future major system upgrades.
- Provides an Ansible Galaxy role [`onlime.policyd_rate_guard`](https://galaxy.ansible.com/onlime/policyd_rate_guard) for easy installation on a Debian mailserver.
- A **well maintained** project, as it is in active use at [Onlime GmbH](https://www.onlime.ch/), a Swiss webhoster with a rock-solid mailserver architecture.

## Requirements

- Debian 13 (trixie) or another Linux with **Python 3.13+** and systemd
- Postfix 3.x with SASL authentication (tested with Postfix 3.10)
- MySQL 8.4+ or MariaDB (tested with MySQL 8.4 and 9.7, MariaDB 12.3)

## Production install 🚀

PolicydRateGuard ships its recommended production setup in `deployment/`: a systemd socket unit (the listening socket survives restarts), a hardened service running as its own user, the daily cleanup timer and a logrotate config. The steps below install it.

> [!TIP]
> To deploy with Ansible, use the role **[`onlime.policyd_rate_guard`](https://github.com/onlime/ansible-role-policyd-rate-guard)** from [Ansible Galaxy](https://galaxy.ansible.com/onlime/policyd_rate_guard). It does all of the following with the same units, including the upgrade from 0.x:
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
>       policyd_yoyo_mysql_pass: '{{ vault_policyd_yoyo_mysql_pass }}'
> ```

### Setup

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
   $ apt install git python3-venv
   $ useradd --system --no-create-home --shell /usr/sbin/nologin policyd-rate-guard
   $ git clone --branch v1.0.0 https://github.com/onlime/policyd-rate-guard.git /opt/policyd-rate-guard
   $ cd /opt/policyd-rate-guard
   $ python3 -m venv venv
   $ venv/bin/pip install --only-binary=:all: .
   ```

3. Configuration in `/etc/policyd-rate-guard/`, readable only by root and the service:

   ```bash
   $ install -d -m 0750 -o root -g policyd-rate-guard /etc/policyd-rate-guard
   $ install -m 0640 -o root -g policyd-rate-guard .env.example /etc/policyd-rate-guard/policyd-rate-guard.env
   $ install -m 0600 -o root -g root yoyo.ini.example /etc/policyd-rate-guard/yoyo.ini
   $ editor /etc/policyd-rate-guard/policyd-rate-guard.env /etc/policyd-rate-guard/yoyo.ini
   $ venv/bin/yoyo apply --config /etc/policyd-rate-guard/yoyo.ini
   $ POLICYD_ENV_FILE=/etc/policyd-rate-guard/policyd-rate-guard.env venv/bin/policyd-rate-guard check
   ```

4. systemd units and log rotation from `deployment/` (for a unix socket instead of `127.0.0.1:10033`, see below):

   ```bash
   $ cp deployment/systemd/* /etc/systemd/system/
   $ cp deployment/logrotate.d/policyd-rate-guard /etc/logrotate.d/
   $ systemctl daemon-reload
   $ systemctl enable --now policyd-rate-guard.socket policyd-rate-guard.service policyd-rate-guard-cleanup.timer
   ```

The daemon gets its listening socket from systemd (`policyd-rate-guard.socket`, `127.0.0.1:10033` by default). The socket stays open while the service restarts, so Postfix's requests wait a moment instead of being answered with the `default_action`.

### Configure Postfix

Integrate PolicydRateGuard with [`check_policy_service`](https://www.postfix.org/postconf.5.html#check_policy_service) in [`smtpd_data_restrictions`](https://www.postfix.org/postconf.5.html#smtpd_data_restrictions) (or `smtpd_end_of_data_restrictions`): only there the recipient count is final. In any other stage the daemon answers `DUNNO` and logs an ERROR, once per stage.

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
- Put it last, after the restrictions that may still reject the mail: a sender under the quota gets `OK`, which ends the restriction list like `permit` (one over the quota gets `DEFER_IF_PERMIT`).

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
3. Move the configuration from `/opt/policyd-rate-guard/.env` to `/etc/policyd-rate-guard/policyd-rate-guard.env`, and `yoyo.ini` to `/etc/policyd-rate-guard/yoyo.ini` with an absolute `sources = /opt/policyd-rate-guard/database/migrations`. Delete the old files, they were world-readable: rotate the passwords, and the webhook secret on both sides at the same time (a mismatch makes every webhook call fail).
4. Replace `run.py`/`cleanup.py` in custom units or scripts with `venv/bin/policyd-rate-guard serve` / `cleanup`.
5. Set `MESSAGE_RETENTION` if you haven't: 0.x kept all messages forever by default. The first cleanup purges the backlog in batches.
6. A unix socket is no longer bound by the daemon: remove `SOCKET=/path` (rejected at startup) and set it up in the socket unit instead (`ListenStream=`, see above).
7. The webhook always sends a JWT: remove `WEBHOOK_USE_JWT=False` and a `{token}` in `WEBHOOK_URL`, and verify the JWT on the receiving side (see below).
8. `LOG_FILE` must be below `/var/log/policyd-rate-guard/`, the only log directory the hardened unit can write to (`LogsDirectory=`). A log file elsewhere makes the service fail at startup.
9. `WEBHOOK_SECRET` must decode to at least 32 bytes (HS256). Generate a new one with `openssl rand -base64 32`.

The database schema is unchanged.

## Configuration ⚙️

All settings are environment variables, usually from `/etc/policyd-rate-guard/policyd-rate-guard.env` (python-dotenv syntax). Another file can be given with `--env-file` or `POLICYD_ENV_FILE`; variables in the process environment take precedence. Invalid values stop the daemon at startup with a list of all errors; `policyd-rate-guard check` validates the configuration and the database connection.

| Variable | Default | Description |
| --- | --- | --- |
| `DB_HOST`, `DB_PORT` | `localhost`, `3306` | Database server (TCP) |
| `DB_UNIX_SOCKET` | | Database unix socket, e.g. `/run/mysqld/mysqld.sock`; overrides host and port |
| `DB_USER`, `DB_PASSWORD`, `DB_DATABASE` | `policyd-rate-guard`, empty, `policyd-rate-guard` | Credentials and database name |
| `DB_POOL_MAXCONNECTIONS` | `10` | Database connections, also the number of requests processed in parallel |
| `DB_POOL_MAXCACHED` | `10` | Idle connections kept in the [DBUtils PooledDB](https://webwareforpython.github.io/DBUtils/main.html#pooleddb-pooled-db-1) pool |
| `DB_LOCK_WAIT_TIMEOUT` | `5` | Seconds (1–7) to wait for a locked row or table before answering `FAIL_ACTION`. A request not decided within 8 s gets `FAIL_ACTION` too, before Postfix's `timeout=10s`. |
| `QUOTA` | `1000` | Default quota (recipients and messages per period) of new senders |
| `ACTION_TEXT_BLOCKED` | `Rate limit reached, retry later` | Text of the `DEFER_IF_PERMIT` answer for senders over quota |
| `FAIL_ACTION` | `DUNNO` | Answer on internal errors (e.g. database down): `DUNNO` (accept) or `DEFER_IF_PERMIT` |
| `SOCKET` | `127.0.0.1,10033` | Only without socket activation: `host,port` (IPv6 as `::1,10033`). A unix socket is set up in the socket unit. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOG_FILE` | | Log file, e.g. `/var/log/policyd-rate-guard/policyd-rate-guard.log` |
| `LOG_CONSOLE`, `SYSLOG` | `False` | Log to stderr (the journal under systemd) and/or syslog (`LOG_MAIL`). Without any of `LOG_FILE`, `LOG_CONSOLE`, `SYSLOG`, logs go to stderr. |
| `MESSAGE_RETENTION` | `0` | Days to keep rows in `messages`; `0` keeps them forever |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | , `dev` | Error reporting to [Sentry](https://sentry.io/) |
| `WEBHOOK_ENABLED` | `False` | Call a webhook when a sender reaches the quota, see below |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | | Webhook URL, shared secret for the JWT (base64, at least 32 bytes) |
| `WEBHOOK_ALLOW_HTTP` | `False` | Allow `http://` webhook URLs (local development only) |

The log line of each counted message has this format (scripts may rely on it):

```
2026-11-08 12:34:56,789 INFO 4XyZ1abc2: client=mail.example.net[192.0.2.10], helo=mail.example.net, sasl_method=PLAIN, sasl_username=user@example.com, from=user@example.com, to=rcpt@example.org, recipient_count=1, curr_count=12/1000, status=ACCEPTED
```

Blocked messages are logged at `WARNING` with `status=BLOCKED`, the one that reached the quota with `status=BLOCKED (QUOTA_LIMIT_REACHED)`. A message counted after Postfix already got `FAIL_ACTION` (no decision within 8 s) shows the answer Postfix got, with `(DECIDE_TIMEOUT)`.

### Configure the API webhook (optional)

PolicydRateGuard can call an external API when a sender reaches the quota, once per period (the first blocked message). The webhook is called after Postfix got its answer, with a 3 s connect and 10 s read timeout, so it can't delay mail; a restart waits for a call in flight for 2 s at most (logged at ERROR if abandoned). It POSTs a JSON object like this:

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
WEBHOOK_URL="https://example.com/api/policyd/{sender}"
WEBHOOK_SECRET="Wk9YZXliVlVtY2pQcFlFUm9KY1U1ZkFFaUpWTk1FU20="
```

Every key of the JSON object can be used as `{placeholder}` in `WEBHOOK_URL` (URL-encoded); unknown placeholders are rejected at startup. `WEBHOOK_URL` must use `https://`. Generate the shared secret (always base64 encoded) like this:

```python
>>> import base64, secrets
>>> base64.b64encode(secrets.token_bytes(32))
```

PolicydRateGuard authenticates with a JWT in the `Authorization: Bearer <JWT>` header, signed with HS256 and the base64-decoded secret, valid for 60 s:

```python
payload = {
    'sub': sender,  # subject, the same as "sender" in the JSON data
    'iss': 'policyd-rate-guard',  # issuer
    'iat': timestamp,  # issued at
    'nbf': timestamp,  # not before
    'exp': timestamp + timedelta(seconds=60),  # expiration time
}
```

Verify it with a JWT library: the signature, the validity (`iat`, `nbf`, `exp`) and that `sub` matches the sender. In a Laravel app, this is usually done in a middleware, with route model binding for the sender (`routes/api.php`):

```php
Route::post('/policyd/{mailaccount:username}', PolicydWebhookController::class)
    ->middleware(AccessApiWebhookPolicyd::class);
```

The middleware, using [`lcobucci/jwt`](https://github.com/lcobucci/jwt) and [`lcobucci/clock`](https://github.com/lcobucci/clock). A missing or invalid token, or one for another sender, gets a 403:

```php
namespace App\Http\Middleware;

use Closure;
use DateInterval;
use Illuminate\Http\Request;
use Lcobucci\Clock\SystemClock;
use Lcobucci\JWT\Exception as JwtException;
use Lcobucci\JWT\JwtFacade;
use Lcobucci\JWT\Signer\Hmac\Sha256;
use Lcobucci\JWT\Signer\Key\InMemory;
use Lcobucci\JWT\Validation\Constraint\SignedWith;
use Lcobucci\JWT\Validation\Constraint\StrictValidAt;
use Symfony\Component\HttpFoundation\Response;

class AccessApiWebhookPolicyd
{
    public function handle(Request $request, Closure $next): Response
    {
        /** @var \App\Models\Mailaccount $mailaccount */
        $mailaccount = $request->route('mailaccount');
        try {
            $sub = new JwtFacade()->parse(
                (string) $request->bearerToken(),
                new SignedWith(new Sha256, InMemory::base64Encoded(config('app.webhooks.secret'))),
                new StrictValidAt(SystemClock::fromSystemTimezone(), new DateInterval('PT10S')), // leeway for clock skew
            )->claims()->get('sub');
        } catch (JwtException) {
            $sub = null;
        }
        abort_if($sub !== $mailaccount->username, 403, 'You are not allowed to access this webhook.');

        return $next($request);
    }
}
```

> [!NOTE]
> For a webhook running on your development machine, use `http://host.docker.internal:8080/…` in `.env.docker` together with `WEBHOOK_ALLOW_HTTP=True`.

## Development 👩‍💻

You need Python 3.13+ and Docker.

```bash
$ git clone https://github.com/onlime/policyd-rate-guard.git
$ cd policyd-rate-guard
$ python3 -m venv .venv
$ . .venv/bin/activate
(.venv)$ pip install -U pip
(.venv)$ pip install --group dev -e .
```

`--group` needs pip 25.1 or later, hence the upgrade first. Optionally, run ruff on every `git push`:

```bash
(.venv)$ pip install pre-commit && pre-commit install
```

The following commands run in the activated venv.

### Tests

The tests come in three levels. Each needs a bit more and tests more of the real thing; CI runs all of them.

| Level | What it tests | Needs | Takes |
| --- | --- | --- | --- |
| Unit | Policy protocol parser, configuration, logging, webhook, Sentry scrubbing, the asyncio server, systemd socket activation | Nothing | Seconds |
| Database | Counting and blocking, 50 parallel first mails of a new sender, quota changes by other tools, the nightly reset and purge, migrations, the CLI (`check`, `cleanup`) | Docker, or any MySQL 8.4+ or MariaDB server | Seconds |
| End-to-end | Real mails through Postfix 3.10 with SASL login: the SMTP reply, the counters, the `messages` row, the log line and the webhook, for a set of mails with To/Cc/Bcc recipients and edge cases | Docker | About a minute (the first build takes a few) |

**Unit tests** run without any setup. Tests that need a database or Postfix are skipped and listed as `SKIPPED` with the reason:

```bash
$ pytest
# one file:
$ pytest tests/test_protocol.py
# the tests matching "webhook", stopping at the first failure:
$ pytest -k webhook -x
```

**Database tests** need `TEST_DATABASE_URL`, a server where the user may create databases: each test run creates a fresh database, applies the migrations and drops it at the end. The compose stack has one (MySQL 8.4 on port 13312):

```bash
$ docker compose up -d --wait db
$ TEST_DATABASE_URL=mysql://root:test@127.0.0.1:13312 pytest --cov
$ docker compose down
```

`--cov` reports the test coverage and fails below 95%, which only the unit and database tests together reach. CI runs them against MySQL 8.4, MySQL 9.7 and MariaDB 12.3 with Python 3.13, and against MySQL 8.4 with Python 3.14. To try another server locally, e.g. MariaDB:

```bash
$ docker run -d --name policyd-test-mariadb -p 13313:3306 -e MARIADB_ROOT_PASSWORD=test mariadb:12.3
# wait until the server accepts connections:
$ sleep 15
$ TEST_DATABASE_URL=mysql://root:test@127.0.0.1:13313 pytest
$ docker rm -f policyd-test-mariadb
```

**End-to-end tests** (`tests/e2e`) send real mails through the compose stack: Postfix on Debian 13 with SASL users `test01@example.com` to `test03@example.com` (password `Example1234`), the daemon, the database and a webhook receiver that records its calls. They need the stack's ports and the three `E2E_` variables:

```bash
$ docker compose up -d --build --wait
$ E2E_SMTP_PORT=1587 E2E_DATABASE_URL=mysql://root:test@127.0.0.1:13312/policyd-rate-guard \
    E2E_WEBHOOK_URL=http://127.0.0.1:18080 pytest tests/e2e
$ docker compose down
```

On GitHub, the end-to-end tests run as their own workflow (E2E) next to CI, on pushes to `main` and `develop` and on pull requests.

The compose stack is also handy to try things by hand: submission on `localhost:1587` (e.g. `swaks --server localhost:1587 --auth PLAIN --auth-user test01@example.com --auth-password Example1234 --to rcpt@example.org`), the daemon's log with `docker compose logs -f policyd`, recorded webhook calls on `http://localhost:18080/calls`.

### Linting and type checking

```bash
$ ruff format .
$ ruff check .
$ mypy
```

### Running the daemon locally

```bash
$ docker compose up -d --wait db
$ docker compose run --rm migrate
$ cp .env.example .env
# in .env: DB_HOST=127.0.0.1, DB_PORT=13312, DB_USER=policyd-rate-guard, DB_PASSWORD=Example1234, LOG_CONSOLE=True,
# and comment out LOG_FILE (its directory only exists on a server)
$ policyd-rate-guard --env-file .env serve
$ policyd-rate-guard --env-file .env cleanup
```

### Dependencies

The direct dependencies are pinned to their minor version (`==X.Y.*`) in `pyproject.toml`, so patch releases come in with the next install. Dependabot proposes updates monthly, and CI runs pip-audit on every push and weekly.

### Database migrations

Migrations are managed with [yoyo](https://ollycope.com/software/yoyo/latest/) in `database/migrations`. Never rename existing migrations, yoyo tracks them by name. Other tools read the tables directly (e.g. an admin UI changing quotas), so keep schema changes backwards compatible.

```bash
$ cp yoyo.ini.docker yoyo.ini
$ yoyo new --sql -m 'update table ratelimits'
$ yoyo apply
```

### Releasing

Update `__version__` in `src/policyd_rate_guard/__init__.py` and `CHANGELOG.md`, push a tag `vX.Y.Z` and create the GitHub release with the changelog section:

```bash
$ git tag -a v1.0.0 -m v1.0.0 && git push origin v1.0.0
$ awk '/^## / { if (f) exit; if (index($0, "[v1.0.0]")) { f = 1; next } } f' CHANGELOG.md > /tmp/release-notes.md
$ gh release create v1.0.0 --verify-tag --title v1.0.0 --notes-file /tmp/release-notes.md
```

## Credits 🙏

**[PolicydRateGuard](https://github.com/onlime/policyd-rate-guard)** is the official successor of [ratelimit-policyd](https://github.com/onlime/ratelimit-policyd) which was running rock-solid for over 10yrs, but suffered the fact that it was built on a shitty scripting language, formerly known as Perl. We consider the switch to Python a huge step up that will ease further development and make you feel at home.

It was greatly inspired by [policyd-rate-limit](https://github.com/nitmir/policyd-rate-limit) (by [@nitmir](https://github.com/nitmir)). PolicydRateGuard has a different feature-set and a much simpler codebase, but things like the daemonizing logic of its first versions were taken from policyd-rate-limit.

## Authors

Made with ❤️ by [Martin Wittwer (Wittwer IT Services)](https://www.wittwer-it.ch/) and [Philip Iezzi (Onlime GmbH)](https://www.onlime.ch/).

## License

This package is licensed under the [GPL-3.0 license](LICENSE); contributions are welcome. Please report security issues as described in [SECURITY.md](SECURITY.md).
