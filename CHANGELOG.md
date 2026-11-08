# CHANGELOG

## [v1.0.0](https://github.com/onlime/policyd-rate-guard/releases/tag/v1.0.0) (unreleased)

A rewrite for Debian 13 (Python 3.13+, Postfix 3.10, systemd 257) with several security fixes. **Upgrade the Ansible role [`onlime.policyd_rate_guard`](https://github.com/onlime/ansible-role-policyd-rate-guard) to v1.0.0 together with this release**: the layout, the service user and the units changed, and role 0.x can't deploy it (see "Upgrading from 0.7.x" in the README).

**Security:**

- **Rate limit bypass by padding:** 0.x read only the first 2048 bytes of a policy request. Postfix sends `helo_name`, `sender`, `client_name` and `reverse_client_name` before `sasl_username`, so an authenticated sender could push `sasl_username` out of the request (e.g. with a 1900-character MAIL FROM local part, which Postfix accepts) and was answered with `DUNNO` without being counted. Requests are now read completely (up to 64 KiB, beyond that `DEFER_IF_PERMIT`), invalid UTF-8 no longer raises.
- **Rate limit bypass by concurrency:** counters were read, incremented in Python and written back as absolute values. Parallel mails of one sender lost updates (30 parallel first mails were counted as 4) and the first mails of a new sender ran into a duplicate key error, answered with `DUNNO`. Counting is now a single atomic upsert; the daemon never writes `quota`, so quota changes made meanwhile (e.g. by an admin tool) are kept.
- A blocked sender's mail was accepted (`DUNNO`) whenever anything failed after the decision, e.g. storing a `From` address longer than 255 characters under strict SQL mode. Values are clamped to the column sizes and the decision is always sent.
- `recipient_count` is validated: a negative value (anyone who can connect to the policy port can send one) reset a sender's counter under non-strict SQL mode.
- Sentry no longer receives local variables of stack frames, which included the webhook secret and the database password; events are scrubbed of email addresses, secrets and tokens.
- Database connect, read, write and lock wait timeouts: a slow or locked database can no longer make requests pile up until the server's connections run out.
- The configuration is read from an explicit file only (`load_dotenv()` searched parent directories) and lives in `/etc/policyd-rate-guard/` instead of the code directory.
- The systemd units run as a dedicated user `policyd-rate-guard` (instead of `postfix`, the mail owner) with full sandboxing (`systemd-analyze security`: 1.1 instead of 9.0).
- Dependencies are installed as binary wheels only, so no third-party code runs at install time.

**Changed (breaking):**

- Requires Python 3.13+ (Debian 13). Only PyMySQL is supported (`DB_DRIVER=sqlite3` is gone, the SQL is MySQL-specific); tested with MySQL 8.4 and 9.7 and MariaDB 12.3.
- Package layout `src/policyd_rate_guard/`; run with `python -m policyd_rate_guard [serve|cleanup|check]`. `run.py`, `cleanup.py`, `setup.py` and `app/` are removed.
- New systemd socket unit `policyd-rate-guard.socket`; the service needs it (`--require-socket-activation`), `Type=notify`.
- `SOCKET` only takes `host,port` (used without socket activation). A unix socket is set up in the socket unit (`ListenStream=/path`), see the README.
- Configuration file `/etc/policyd-rate-guard/policyd-rate-guard.env` (or `--env-file`/`POLICYD_ENV_FILE`). The variable names are unchanged, but invalid values now stop the daemon at startup with a list of all errors.
- `LOG_MSG_PREFIX` is removed. The log line format is unchanged; the queue ID prefix stays.
- Webhook: `https://` is required unless `WEBHOOK_ALLOW_HTTP=True`; placeholders in `WEBHOOK_URL` are URL-encoded and checked at startup; `rcpt_count` in the payload is an integer.
- Webhook: the simple token (`sha256(secret + sender)` in the `{token}` placeholder, static and replayable) is removed. The webhook always sends a JWT in the `Authorization: Bearer` header, with the same claims as before; `WEBHOOK_USE_JWT=False` and `{token}` are rejected at startup. `WEBHOOK_SECRET` must be base64 encoded.
- `DB_POOL_MAXSHARED` is ignored (PyMySQL connections can't be shared).

**Improved:**

- asyncio server with persistent connections, as Postfix's policy protocol expects (0.x closed the connection after each request), idle timeout and graceful shutdown on `SIGTERM`; database work runs in a bounded thread pool, requests without `sasl_username` (inbound mail) are answered without the database.
- systemd socket activation: the listening socket survives restarts, Postfix's connections wait instead of falling back to `DUNNO`.
- The webhook is called after the reply to Postfix, in its own thread, with timeouts.
- Correct queue IDs in the log under concurrency (0.x shared them across threads). The log line format is unchanged.
- The log file is reopened after rotation, logrotate no longer restarts the daemon.
- The webhook payload's `timestamp` is the time of the message (0.x always sent the daemon's start time).
- Daily cleanup resets counters in one statement and purges old messages in batches.
- A warning if the daemon is not used in the DATA or END-OF-MESSAGE stage, where the recipient count is final.

**Added:**

- `DB_UNIX_SOCKET`, `DB_POOL_MAXCONNECTIONS`, `DB_LOCK_WAIT_TIMEOUT`, `FAIL_ACTION`, `WEBHOOK_ALLOW_HTTP`.
- `check` command to validate the configuration and the database connection (used by the Ansible role before restarting).

**Development:**

- pyproject.toml with the dependencies pinned to minor versions, installed with plain pip (also in production, `pip install .`). ruff (also as pre-commit hook) and mypy, pytest (unit, concurrency, database and end-to-end tests through a real Postfix), GitHub Actions for MySQL 8.4, MySQL 9.7 and MariaDB 12.3 on Python 3.13 (and 3.14), pip-audit and Dependabot.

## [v0.7.4](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.7.4) (2026-02-24)

**Improved:**

- Updated docker-compose `policyd` service Docker image from `python:3.11` to `python:3.13`
- Updated docker-compose `db` service Docker image from `mysql:8.0` to `mysql:8.4`
- Removed legacy `distutils` dependency and replaced `strtobool` implementation with a custom one
- Upgraded packages: DBUtils 3.1.2, cryptography 46.0.5, PyMySQL 1.1.2, python-dotenv 1.0.2, requests 2.32.5, sentry-sdk 2.53.0

## [v0.7.3](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.7.3) (2024-05-21)

**Improved:**

- Improved PEP8 Python code style: Added configuration for [YAPF](https://github.com/google/yapf) and applied yapf formatting rules.
- Upgraded packages: DBUtils 3.1.0, cryptography 42.0.7, PyMySQL 1.1.1, python-dotenv 1.0.1, requests 2.32.2, sentry-sdk 2.2.1

**Security:**

- **It is strongly recommended to upgrade all pip packages, as [PyMySQL 1.1.1](https://github.com/PyMySQL/PyMySQL/releases/tag/v1.1.1) fixes a SQL Injection vulnerability ([CVE-2024-36039](https://github.com/advisories/GHSA-v9hf-5j83-6xpp)).**


## [v0.7.2](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.7.2) (2023-09-11)

**Improved:**

- Webhook authentication token type (Simple hashed token vs. JWT token) can now be configured with new env var `WEBHOOK_USE_JWT` and no longer depends on whether you pass the token as query param (not recommended for JWT tokens) or `Authorization: Bearer` header.
- Webhook JWT token now contains all necessary claims for strict verification: `sub` (Subject), `iss` (Issuer), `iat` (Issued At), `nbf` (Not Before), `exp` (Expiration Time).

**Fixed:**

- Webhook JWT token is now correctly encoded using base64 decoded secret (`WEBHOOK_SECRET`) as key. Previously, we forgot to decode it, but always recommended (and still do!) to use a base64 encoded secret.

## [v0.7.1](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.7.1) (2023-09-11)

**Improved:**

- You can now use any key of the passed JSON object (payload of the POST request) in your `WEBHOOK_URL` as a placeholder. All placeholders are optional.
- Added `Accept: application/json` header to webhook POST requests.

## [v0.7.0](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.7.0) (2023-09-08)

**Improved:**

- Updated docker-compose `policyd` service Docker image from `python:3.8` to `python:3.11`
- Improved Python code style by fixing all Flake8 linting warnings.

**Added:**

- Added configurable webhook API call to trigger sender notification when reaching his quota limit (on first block). For authentication, it supports both simple token (passed as query param) and JWT token (passed as `Authorization: Bearer` header).
- Added new environment variables for external webhook API: `WEBHOOK_ENABLED`, `WEBHOOK_URL`, `WEBHOOK_SECRET`

**Fixed:**

- Prevent multiple logger instances by accessing a static `logger` variable. This fixes `ResourceWarning: unclosed file` exceptions which could have occurred in testing.

## [v0.6.1](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.6.1) (2023-09-06)

**Improved:**

- Code cleanup: Using relative imports.
- Code cleanup: Simplified parsing of data using dict comprehension in `Handler`.
- Refactoring: moved `PrefixedLogger` class into its own file.

**Added:**

- Database cleanup job now also purges old messages, if enabled through `MESSAGE_RETENTION` env var.
- Introduced new environment variable `MESSAGE_RETENTION` to control number of days to keep messages in the database. Defaults to `0` (keep forever).

## [v0.6.0](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.6.0) (2023-09-01)

**Improved:**

- Improved performance and stability by introducing database connection pooling, using [DBUtils PooledDB (pooled_db)](https://webwareforpython.github.io/DBUtils/main.html#pooleddb-pooled-db)
- Moved logger and db cleanup code into destructor of `Handler`.
- Refactored `database.db` to `app.db` to simplify project structure.

**Added:**

- Added environment variables `DB_POOL_MINCACHED`, `DB_POOL_MAXCACHED`, `DB_POOL_MAXSHARED`, `DB_POOL_MAXUSAGE` for db connection pooling fine-tuning.

**Fixed:**

- Fix `Lost connection to MySQL server during query ` and ``AttributeError: 'NoneType' object has no attribute 'read'` (on db cursor) connectivity issues by introducing connection pooling.

## [v0.5.1](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.5.1) (2023-08-30)

**Added:**

- Added `LOG_MSG_PREFIX` (boolean) environment variable which is enabled by default. Prefix all log messages with a prefix containing information about the calling filename, class, and function name, e.g. `ratelimit.py Ratelimit.update() - `.
- Always prepend log messages with message ID (Postfix `queue_id`) if available, independent from `LOG_MSG_PREFIX` feature being enabled/disabled.

**Fixed:**

- Fix edge case where `sasl_username` was set in Postfix DATA but empty. We now bail out early if `sasl_username` either does not exist or is empty.

## [v0.5.0](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.5.0) (2023-08-29)

Initial release with the following feature set:

- **Super easy Postfix integration** using `check_policy_service` in `smtpd_data_restrictions`
- Set **individual sender (SASL username) quotas**
- Limit senders to **number of recipients** per time period
- Automatically fills `ratelimits` table with new senders (SASL username) upon first email sent
- Set your own time period (usually 24hrs) by resetting the counters via Systemd cleanup timer (or cronjob)
- Continues to raise counters (`msg_counter`, `rcpt_counter`) even in over quota state, so you know if a sender keeps retrying/spamming.
- Keeps totals of all messages/recipients sent for each sender (SASL username)
- Stores both **message and recipient counters** in database (`ratelimits` table)
- Stores **detailed information for all sent messages** (`msgid, sender, rcpt_count, blocked, from_addr, client ip, client hostname`) in database (`messages` table)
- **Logs detailed message information to Syslog** (using `LOG_MAIL` facility, so the logs end up in `mail.log`)
- **Maximum failure safety:** On any unexpected exception, the daemon still replies with a `DUNNO` action, so that the mail is not getting rejected by Postfix. This is done both on Postfix integration side and application exception handling side.
- **Block action message** `"Rate limit reached, retry later."` can be configured.
- Lots of configuration params via a simple `.env`
- **Tuned for high performance**, using network or unix sockets, and threading.
- **Secure setup**, nothing running under `root`, only on `postfix` user.
- A super slick minimal codebase with **only a few dependencies** ([PyMySQL](https://pypi.org/project/pymysql/), [python-dotenv](https://pypi.org/project/python-dotenv/), [yoyo-migrations](https://pypi.org/project/yoyo-migrations/)), using Python virtual environment for easy `pip` install. PyMySQL is a pure-Python MySQL client library, so you won't have any trouble on any future major system upgrades.
- Provides an Ansible Galaxy role [`onlime.policyd_rate_guard`](https://galaxy.ansible.com/onlime/policyd_rate_guard) for easy installation on a Debian mailserver.
- A **well maintained** project, as it is in active use at [Onlime GmbH](https://www.onlime.ch/), a Swiss webhoster with a rock-solid mailserver architecture.
