# CHANGELOG

## [v0.7.4](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.7.4) (unreleased)


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
