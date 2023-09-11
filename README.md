![PolicydRateGuard logo](./docs/logo-dark.png#gh-dark-mode-only)
![PolicydRateGuard logo](./docs/logo-light.png#gh-light-mode-only)

# PolicydRateGuard

[![CI status](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/onlime/policyd-rate-guard)](https://github.com/onlime/policyd-rate-guard/releases)

A slick sender rate limit policy daemon for Postfix, written in Python.

©2023 by [Onlime GmbH](https://www.onlime.ch/) – Your Swiss webhosting provider living the "no BS" philosophy!

## Features ✨

Actually, PolicydRateGuard is just a super simple Postfix policy daemon with only one purpose: Limit senders by messages/recipients sent.

But let me name some features that make it stand out from other solutions:

- **Super easy Postfix integration** using `check_policy_service` in `smtpd_data_restrictions`
- **Tuned for high performance**, using network or unix sockets, threading, and db connection pooling.
- Set **individual sender (SASL username) quotas**, which can be both persistent or only for the current time period.
- Limit senders to **number of recipients** per time period
- Automatically fills `ratelimits` table with new senders (SASL username) upon first email sent
- Set your own **time period (usually 24hrs)** by resetting the counters via Systemd cleanup timer (or cronjob)
- Continues to raise counters (`msg_counter`, `rcpt_counter`) even in over quota state, so you know if a sender keeps retrying/spamming.
- Keeps totals of all messages/recipients sent for each sender (SASL username)
- Stores both **message and recipient counters** in database (`ratelimits` table)
- Stores **detailed information for all sent messages** (`msgid, sender, rcpt_count, blocked, from_addr, client ip, client hostname`) in database (`messages` table)
- **Logs detailed message information to Syslog** (using `LOG_MAIL` facility, so the logs end up in `mail.log`)
- **Maximum failure safety:** On any unexpected exception, the daemon still replies with a `DUNNO` action, so that the mail is not getting rejected by Postfix. This is done both on Postfix integration side and application exception handling side.
- **Block action message** `"Rate limit reached, retry later."` can be configured.
- Lots of configuration params via a simple `.env` 
- **Secure setup**, nothing running under `root`, only on `postfix` user.
- A multi-threaded app that uses [DBUtils PooledDB (pooled_db)](https://github.com/WebwareForPython/DBUtils) for **robust and efficient DB connection handling**.
- Can be used with any [DB-API 2 (PEP 249)](https://peps.python.org/pep-0249/) conformant database adapter (currently supported: PyMySQL, sqlite3)
- A super slick minimal codebase with **only a few dependencies** ([PyMySQL](https://pypi.org/project/pymysql/), [DBUtils](https://webwareforpython.github.io/DBUtils/), [python-dotenv](https://pypi.org/project/python-dotenv/), [yoyo-migrations](https://pypi.org/project/yoyo-migrations/)), using Python virtual environment for easy `pip` install. PyMySQL is a pure-Python MySQL client library, so you won't have any trouble on any future major system upgrades.
- **Supports external API webhooks** with simple token based authentication (passed as query param) or JWT token (passed as `Authorization: Bearer` header). When configured, the webhook is triggered whenever a sender reaches his quota limit for the first time and you can send out notification through your own or any 3rd-party app.
- Provides an Ansible Galaxy role [`onlime.policyd_rate_guard`](https://galaxy.ansible.com/onlime/policyd_rate_guard) for easy installation on a Debian mailserver.
- A **well maintained** project, as it is in active use at [Onlime GmbH](https://www.onlime.ch/), a Swiss webhoster with a rock-solid mailserver architecture.

## Production INSTALL 🚀

> [!IMPORTANT]  
> We provide an **[Ansible Galaxy](https://galaxy.ansible.com/onlime/policyd_rate_guard) role [`onlime.policyd_rate_guard`](https://github.com/onlime/ansible-role-policyd-rate-guard)** for a simple automated installation on a Debian mailserver. So instead of following the **Setup** instructions below, you could run:
>
> ```bash
> $ ansible-galaxy install onlime.policyd_rate_guard
> ```
>
> Then create some `policyd-rate-guard.yml` playbook like e.g.:
> ```yaml
> - hosts: smtphosts
>   roles:
>     - role: onlime.policyd_rate_guard
>       policyd_mysql_pass: '{{ vault_policyd_mysql_pass }}'
> ```
>
> And then deploy like this:
> ```bash
> $ ansible-playbook policyd-rate-guard.yml
> ```

### Requirements

You need a running MySQL/MariaDB server and a running Postfix server with SASL auth to use this daemon. It might work under lower versions, but it was tested under the following:

- Postfix 3.5+
- MySQL 8.0+
- Python 3.9+

In addition to MySQL/MariaDB, it also supports Sqlite3, but this is currently untested.

### Setup

To setup PolicydRateGuard and run the daemon in production, follow this:

> [!NOTE]  
> Remember, there's an Ansible Galaxy role [`onlime.policyd_rate_guard`](https://galaxy.ansible.com/onlime/policyd_rate_guard) for all this, if you don't like it the manual way!

1. Prepare MySQL database `policyd-rate-guard` and user `policyd-rate-guard`:

```sql
mysql> CREATE DATABASE `policyd-rate-guard`;
mysql> CREATE USER `policyd-rate-guard`@localhost IDENTIFIED BY 'Pa55w0rd';
mysql> GRANT ALL ON `policyd-rate-guard`.* TO `policyd-rate-guard`@localhost;
```

2. Copy/clone project to server (we assume `/opt/policyd-rate-guard`)

```bash
$ cd /opt
$ git clone https://github.com/onlime/policyd-rate-guard.git
```

3. Create a virtualenv and install the requirements:

```bash
$ cd /opt/policyd-rate-guard
$ python3 -m venv .venv
$ . .venv/bin/activate
(venv)$ pip install --upgrade pip
(venv)$ pip install -r requirements.txt
(venv)$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
(venv)$ yoyo apply # Run the database migrations
(venv)$ cp .env.example .env # & Adjust the settings
```

4. Install logrotation config and copy the Systemd service files to `/etc/systemd/system/`:

```bash
$ cp development/logrotate.d/* /etc/logrotate.d/
$ cp deployment/systemd/* /etc/systemd/system/
```

5. Enable and start the Systemd services:

```bash
$ systemctl daemon-reload
$ systemctl start policyd-rate-guard.service # Start the daemon
$ systemctl enable policyd-rate-guard.service # Enable the daemon to start on boot
$ systemctl start policyd-rate-guard-cleanup.timer # Start the cleanup timer
$ systemctl enable policyd-rate-guard-cleanup.timer # Enable the cleanup timer
```

It's recommended to enable `SYSLOG` logging on production in `.env`:

```ini
SYSLOG=True
```

On any configuration changes, restart `policyd-rate-guard` and make sure it's running:

```bash
$ systemctl restart policyd-rate-guard
$ systemctl status policyd-rate-guard
```

### Configure Postfix

We recommend to integrate PolicydRateGuard directly into Postfix using the [`check_policy_service`](https://www.postfix.org/postconf.5.html#check_policy_service) restriction in [`smtpd_data_restrictions`](https://www.postfix.org/postconf.5.html#smtpd_data_restrictions).

`/etc/postfix/main.cf`:

```
smtpd_data_restrictions =
        reject_unauth_pipelining,
        check_policy_service { inet:127.0.0.1:10033, default_action=DUNNO },
        permit 
```

**IMPORTANT:** We strongly recommend the advanced policy client configuration (supported since Postfix 3.0), using above syntax with **default action `DUNNO`**, instead of just using `check_policy_service inet:127.0.0.1:10033`.

It ensures that if PolicydRateGuard becomes unavailable for any reason, Postfix will ignore it and keep accepting mail as if the rule was not there. PolicydRateGuard should be considered a "non-critical" policy service and you should use some monitoring solution to ensure it is always running as expected.

> [!NOTE]
> You may use `unix:rateguard/policyd` instead of `inet:127.0.0.1:10033` if you have configured PolicydRateGuard to use a unix socket (`SOCKET="/var/spool/postfix/rateguard/policyd"` environment variable).

Make sure to reload Postfix after this change:

```bash
$ systemctl reload postfix
```

> [!IMPORTANT]
> In Postfix, when multiple recipients are specified in the `To:` field of an email, the Postfix policy delegation protocol (the `check_policy_service` action in this case) doesn't include each individual recipient separately by default. Instead, it sends a single `recipient=` line with an empty value to indicate that there are recipients but doesn't list them individually.
> There is no way for **PolicydRateGuard** to register any recipients, neither in the log message nor in the `messages` db table, if a message was sent to multiple email addresses in `To:`. Also, there is no way to register any recipients from `Cc:` and/or `Bcc:` headers.
>
> But aside this little drawback, Postfix integration using [`check_policy_service`](https://www.postfix.org/postconf.5.html#check_policy_service) is simply the best and probably the only way to go. Currently, this is the only supported way to configure it!

### Upgrade

You can run an upgrade with the Ansible Galaxy playbook you have created above, using our [`onlime.policyd_rate_guard`](https://galaxy.ansible.com/onlime/policyd_rate_guard) role:

```bash
$ ansible-playbook policyd-rate-guard.yml
```

Or you might as well just do a `git pull` upgrade directly on your production mail server:

```bash
$ cd /opt/policyd-rate-guard
$ git pull

# And if anything in database/migrations or requirements.txt has changed:
$ . venv/bin/activate
(venv)$ pip install -r requirements.txt
(venv)$ yoyo apply

# Finally restart the service
$ systemctl restart policyd-rate-guard.service
```

You don't need to worry about any short downtime for this upgrade process, as it will only take some seconds, and anyway the daemon can be gone for a while without any impact on your Postfix deliverability, as long as you have set it up correctly using the `default_action=DUNNO` trick (see «Configure Postfix» section above).

## Configuration ⚙️

### Environment Variables `.env`

PolicydRateGuard can be fully configured through environment variables in `.env`. The following are supported:

- `DB_DRIVER`
  The database driver to use, either `pymysql` or `sqlite3`. [PyMySQL](https://pypi.org/project/pymysql/) is a pure-Python MySQL client library, based on [PEP 249](https://peps.python.org/pep-0249/). It's greatly recommended to stick with this driver, as PolicydRateGuard is currently only tested under MySQL using this driver. The default is `pymysql`.
- `DB_HOST`
  The database hostname. Defaults to `localhost`.
- `DB_PORT`
  The database port. Defaults to `3306`.
- `DB_USER`
  The database username. Defaults to `policyd-rate-guard`.
- `DB_PASSWORD`
  The database password. Defaults to `""`.
- `DB_DATABASE`
  The database name. Defaults to `policyd-rate-guard` (for `DB_DRIVER=pymsql`) or `:memory:` (for `DB_DRIVER=sqlite3`).
- `SOCKET`
  The socket to bind to. Can be a path to an unix socket or a couple [ip, port]. The default is `"127.0.0.1,10033"`. If you prefer using a unix socket, the recommended path is `"/var/spool/postfix/rateguard/policyd"`. PolicydRateGuard will try to create the parent directory and chown it if it do not exists.
- `QUOTA`
  The default quota for a user. Defaults to `1000`.
- `ACTION_TEXT_BLOCKED`
  Here you can put a custom message to be shown to a sender who is over his ratelimit. Defaults to `"Rate limit reached, retry later."`.
- `LOG_LEVEL`
  Set the level of the logger. Possible values: `DEBUG, INFO, WARNING, ERROR, CRITICAL`. Defaults to `INFO`.
- `LOG_FILE`
  Set a logfile path, e.g. `/var/log/policyd-rate-guard/policyd-rate-guard.log`. This can be used in addition to enabling `SYSLOG` and/or `LOG_CONSOLE`, to log into a separate log file. Defaults to `None` (commented out).
- `LOG_MSG_PREFIX`
  Prefix all log messages with a prefix containing information about the calling filename, class, and function name, e.g. `ratelimit.py Ratelimit.update() - `. We recommend to disable this on a production deployment (as it's more kind of debug information that shouldn't bloat our logs). Defaults to `True`.
- `LOG_CONSOLE` (bool)
  Send logs to console (on `stderr`). This can be used in addition to enabling `LOG_FILE` and/or `SYSLOG`. Possible values: `True` or `False`. Defaults to `False`.
- `SYSLOG` (bool)
  Send logs to syslog. Possible values: `True` or `False`. Defaults to `False`.
- `MESSAGE_RETENTION`
  How many days to keep messages in the database. Defaults to `0` (never delete).

You may also tune the database connection pooling by modifying the following environment variables (defaults are fine for most environments, and you'll find e detailed description in the [DBUtils PooledDB](https://webwareforpython.github.io/DBUtils/main.html#pooleddb-pooled-db-1) usage docs):

- `DB_POOL_MINCACHED` (default: `0`)
- `DB_POOL_MAXCACHED` (default: `10`
- `DB_POOL_MAXSHARED` (default: `10`)
- `DB_POOL_MAXUSAGE`  (default: `10000`)

Optional configuration for external service integration:

- `SENTRY_DSN`
  Your Sentry DSN in the following form: `https://**********.ingest.sentry.io/XXXXXXXXXXXXXXXX`. Defaults to `None` (Sentry exception reporting disabled).
- `SENTRY_ENVIRONMENT`
  Sentry environment. Suggested values: `dev` or `prod`, but can be any custom string. Defaults to `dev`.
- `WEBHOOK_ENABLED` (bool)
  Enable external API webhook to be called when sender reached his quota limit (first time he's blocked). Possible values: `True` or `False`. Defaults to `False`.
- `WEBHOOK_URL`
  Webhook API URL of the external service that should be called if `WEBHOOK_ENABLED=True`. It supports the following placeholders, which are both optional: `{sender}`, `{token}`. You may provide a URL in the following form: `https://api.example.com/policyd/{sender}?token={token}` (the token will be a simple hash from your secret appended to the sender address), or if you omit the `{token}` in the URL, a signed JWT token will be passed as `Bearer` token in the `Authorization` header, which will also contain the sender in its payload.
- `WEBHOOK_SECRET`
  The shared secret to generate the webhook token. Configure this shared secret also on the external API's webhook to verify the token for authentication. Recommended way to generate a secret: `base64.b64encode(secrets.token_bytes(32))`

For production, we recommend to start by copying `.env.example` and then fine-tune your `.env`:

```bash
$ cp .env.example .env
```

> [!NOTE]
> Minimally, you should set `DB_PASSWORD`, and maybe enable `SYSLOG` logging. For all the other config params it's usually fine to stick with the defaults.

### Configure API Webhook (optional)

You may configure PolicydRateGuard to call an external API webhook when a sender reaches his quota limit. This will only be triggered the first time a sender runs over his limit. The POST request contains a JSON object with the following data (sample data):

```json
{
    "msgid": "TEST1234567",
    "sender": "demo1@example.com",
    "client_address": "172.19.0.2",
    "client_name": "unknown",
    "rcpt_count": 10,
    "from_addr": "test-from@example.com",
    "to_addr": "test-to@example.com",
    "timestamp": "2023-09-07 12:34:56",
    "quota": 1000,
    "quota_reset": 1000,
    "used": 1005
}
```

You can configure it in your `.env` like this:

```ini
WEBHOOK_ENABLED=True
WEBHOOK_URL="https://example.com/api/policyd/{sender}?token={token}"
WEBHOOK_SECRET="Wk9YZXliVlVtY2pQcFlFUm9KY1U1ZkFFaUpWTk1FU20="
```
Every key of above JSON object can also be used as placeholder in `WEBHOOK_URL`, using the following syntax: `{KEY}`. All placeholders are optional. Additionally, you can include the special placeholder `{token}` in `WEBHOOK_URL` to pass the authentication token as query param. See explanation in Variant 1 vs. 2 below.

> [!IMPORTANT]
> On production, make sure you always just use `https://` in your `WEBHOOK_URL`, so the token is never getting exposed!

> [!NOTE]
> If you have your external API webhook running in your development environment, running on the same host where you run your `docker-compose` services (see Development guide below), you may use `host.docker.internal` to access your host. There's no need to map any extra ports in `docker-compose.yml`. If your API webhook runs on `localhost:8080`, you would simple put the following `WEBHOOK_URL` in `.env.docker`:
>
> ```ini
> WEBHOOK_URL="http://host.docker.internal:8080/api/policyd/{sender}?token={token}"
> ```

You can generate the shared secret for `WEBHOOK_SECRET` like this in Python (`python3` interactive shell):

```python
>>> import base64
>>> import secrets
>>> base64.b64encode(secrets.token_bytes(32))
```

or with PHP (e.g. using `php artisan tinker` in Laravel, or `php -a` interactive shell):

```php
> base64_encode(Str::random(32))
```

Depending on your external API, PolicydRateGuard supports two different ways of authentication:

**Variant 1) Simple token as query param**

The authentication token can be passed as a query param to your external API webhook. In this case, you need to use the `{token}` placeholder in your `WEBHOOK_URL`, no matter if you use any other (optional) placeholders like  `{sender}` or not. The sender will always be part of the JSON data (payload) passed to your webhook anyway.

In this case, the token will be generated like this (pseudo-code):

````python
sha256('{secret}{sender}')
````

The token would then need to get verified on the external API webhook in the same way, using the same shared secret.

In a Laravel app, authentication will usually be done in a middleware, and we want to use route model binding for the `sender`.

```php
class PolicydWebhookController extends Controller
{
    public function __invoke(PolicydLimitReachedRequest $request, Mailaccount $mailaccount)
    {
        // TODO: send notification to $mailaccount owner
        return ['success' => true];
    }
}
```

the route would look somewhat like this (`routes/api.php`):
```php
Route::post('/policyd/{mailaccount:username}', PolicydWebhookController::class)
    ->middleware(AccessApiWebhookPolicyd::class);
```

and you would run the authentication check in your `AccessApiWebhookPolicyd` middleware:

```php
class AccessApiWebhookPolicyd
{
    public function handle(Request $request, Closure $next): Response
    {
        /** @var App\Models\Mailaccount $mailaccount */
        $mailaccount = $request->route('mailaccount');
        $token = hash('sha256', config('app.webhooks.secret').$mailaccount->username);
        if ($request->query('token') !== $token) {
            abort(403, 'You are not allowed to access this webhook.');
        }
        return $next($request);
    }
}
```

**Variant 2) JWT token in Authorization header**

If your `WEBHOOK_URL` does not contain a `{token}` placeholder, we assume you don't want to pass it as query param, but as JWT token in the `Authorization: Bearer <token>` header instead. PolicydRateGuard will take care of it and generate a valid JWT token, basically like this:

```python
import jwt
from datetime import datetime, timedelta, timezone
payload = {
    'sub': sender,
    'exp': datetime.now(tz=timezone.utc) + timedelta(seconds=60)
}
return jwt.encode(payload, secret, algorithm='HS256')
```

The token is valid for 60s and contains the `sub` (subject, in our case the `sender`) in its payload. The subject in the JWT token is always the same as the `sender` in the JSON data passed via POST request.

If your external API webhook runs on PHP, we recommend to use the [`lcobucci/jwt`](https://github.com/lcobucci/jwt) library to decode and verify the JWT token. In a Laravel app you can go for a similar implementation as described in Variant 1) and decode the JWT token in your `AccessApiWebhookPolicyd` middleware.

## Development 👩‍💻

### Initial setup

To set up a basic developer environment, run the following commands:

```bash
$ git clone git@gitlab.onlime.ch:onlime/policyd-rate-guard.git
$ cd policyd-rate-guard
$ python3 -m venv .venv
$ . .venv/bin/activate
(venv)$ pip install --upgrade pip
(venv)$ pip install -r requirements.txt
$ docker-compose up -d db
(venv)$ cp .env.example .env
(venv)$ cp yoyo.ini.docker yoyo.ini
(venv)$ yoyo apply
```

### Running the daemon

#### Local

To run the daemon, run the following commands:

If needed start the testing DB:

```bash
$ docker-compose up -d db
```

Then run the daemon:

```bash
$ cp .env.example .env # & Adjust the settings
$ cp yoyo.ini.docker yoyo.ini # & Adjust the settings
(venv)$ yoyo apply
(venv)$ python3 run.py
```

To cleanup (reset all counters and quotas and purge old messages if `MESSAGE_RETENTION` is set) the database, run:

```bash
(venv)$ python3 cleanup.py
```

> You could manually connect to MySQL like this (or with a GUI tool like [TablePlus](https://tableplus.com/)):
>
> ```bash
> # connect as root
> $ mysql -h 127.0.0.1 -P 13312 -u root --password=test policyd-rate-guard
> # connect as policyd-rate-guard
> $ mysql -h 127.0.0.1 -P 13312 -u policyd-rate-guard --password=Example1234 policyd-rate-guard
> ```

#### Docker

To run a full test environment with a postfix with SASL auth and a policyd-rate-guard daemon, run the following commands:

1. You have to seed the database before running the daemon. This is done like that:

```bash
$ docker-compose up -d db
$ cp yoyo.ini.docker yoyo.ini # & Adjust the settings
(venv)$ yoyo apply

# if needed, restart from scratch like this (lookup container name with `docker container ls -a`):
$ docker-compose stop db
$ docker rm policyd-rate-guard-db-1
```

2. Then run the daemon:

```bash
$ docker-compose build
$ docker-compose up -d
```

Or only run Postfix and Policyd:

```bash
$ docker-compose up postfix policyd # No daemon so you see logs and can stop it with CTRL+C
```

3. With a SMTP client connect to `localhost:1025` with user `test01@example.com` and password `Example1234` and send some mails.

4. Cleanup with this command:

```bash
$ docker-compose exec policyd python3 cleanup.py
```

### Running the tests

To run the tests, run the following commands (you only need the `db` container running):

```bash
$ docker-compose up -d db
$ cp yoyo.ini.docker yoyo.ini # & Adjust the settings
$ . venv/bin/activate
(venv)$ yoyo apply
(venv)$ ./tests.sh
```

> [!IMPORTANT]
> Make sure to always run the tests inside your venv!

### Linting with flake8

You can run Python code style linting with [Flake8](https://flake8.pycqa.org/) locally in your venv:

```bash
$ . venv/bin/activate
(venv)$ pip install flake8
(venv)$ flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics --exclude=venv
```

The same will also be done in our [Github workflow `ci.yml`](https://github.com/onlime/policyd-rate-guard/actions/workflows/ci.yml).

### Configure Sentry SDK

Sentry integration can be both used in your development environment and on production.

1. Create new project `policyd-rate-guard` on [Sentry](https://sentry.io/)
2. Copy-paste your Sentry project DSN into your `.env` (and/or `.env.docker`, `.env.test`)
3. done.

On a development `.env.docker` you should enable Sentry by commenting out those lines:

```ini
SENTRY_DSN=https://**********.ingest.sentry.io/XXXXXXXXXXXXXXXX
SENTRY_ENVIRONMENT=docker
```

On production, use the same DSN and configure it in `.env`:

```ini
SENTRY_DSN=https://**********.ingest.sentry.io/XXXXXXXXXXXXXXXX
SENTRY_ENVIRONMENT=prod
```

**Verify:** One way to verify your setup is by intentionally causing an error that breaks the application. Raise an unhandled Python exception by inserting a divide by zero expression anywhere in the application code (e.g. somewhere at the end of `Handler.handle()` method):

```python
division_by_zero = 1 / 0
```

### Create DB migrations

In venv, use the [`yoyo new`](https://ollycope.com/software/yoyo/latest/#yoyo-new) command to create a new migration:

```bash
(venv)$ yoyo new --sql -m 'update table ratelimits'
```

The migration will be placed in `database/migrations` directory. After having written the migration statements, apply the migration like this:

```bash
(venv)$ yoyo apply
```

## TODO ✅

Planned features (coming soon):

- [x] Define **Syslog facility** `LOG_MAIL`, **ident** `policyd-rate-guard`, and additionally log to `/var/log/policyd-rate-guard.log`
- [x] **Sentry** integration for exception reporting
- [x] **Ansible role** for easy production deployment
- [x] **Github workflow** for CI/testing
- [x] **Message retention**: Expire/purge old messages, configurable via env var `MESSAGE_RETENTION` (defaults to keep forever)
- [x] Implement a **configurable webhook API** call for notification to sender on reaching quota limit (on first block) to external service.
- [ ] **Publish package** to [PyPI](https://pypi.org/) (Might need some restructuring. Any help greatly appreciated!)

## Credits 🙏

**[PolicydRateGuard](https://github.com/onlime/policyd-rate-guard)** is the official successor of [ratelimit-policyd](https://github.com/onlime/ratelimit-policyd) which was running rock-solid for the last 10yrs, but suffered the fact that it was built on a shitty scripting language, formerly known as Perl. We consider the switch to Python a huge step up that will ease further development and make you feel at home.

It was greatly inspired by [policyd-rate-limit](https://github.com/nitmir/policyd-rate-limit) (by [@nitmir](https://github.com/nitmir)). PolicydRateGuard has a different feature-set and a much simpler codebase, but thing like the daemonizing logic were taken from policyd-rate-limit.

## Authors

Made with ❤️ by [Martin Wittwer (Wittwer IT Services)](https://www.wittwer-it.ch/) and [Philip Iezzi (Onlime GmbH)](https://www.onlime.ch/).

## License

This package is licenced under the [GPL-3.0 license](LICENSE) however support is more than welcome.
