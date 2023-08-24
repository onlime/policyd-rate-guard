# PolicydRateGuard

A slick sender rate limit policy daemon for Postfix, written in Python.

©2023 by [Onlime GmbH](https://www.onlime.ch/) – Your Swiss webhosting provider living the "no BS" philosophy!

## Production INSTALL

### Requirements

You need a running MySQL/MariaDB server and a running Postfix server with SASL auth to use this daemon. It might work under lower versions, but it was tested under the following:

- Postfix 3.5+
- MySQL 8.0+
- Python 3.9+

In addition to MySQL/MariaDB, it also supports Sqlite3, but this is currently untested.

### Setup

To run the daemon in production, follow this:

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
$ python3 -m venv venv
$ . venv/bin/activate
(venv)$ pip install --upgrade pip
(venv)$ pip install -r requirements.txt
(venv)$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
(venv)$ yoyo apply # Run the database migrations
(venv)$ cp .env.example .env # & Adjust the settings
```

4. Copy the Systemd service files to `/etc/systemd/system/`:

```bash
$ cp deployment/systemd_daemon.service /etc/systemd/system/policyd-rate-guard.service
$ cp deployment/systemd_cleanup.service /etc/systemd/system/policyd-rate-guard-cleanup.service
$ cp deployment/systemd_cleanup.timer /etc/systemd/system/policyd-rate-guard-cleanup.timer
```

5. Enable and start the Systemd services:

```bash
$ systemctl daemon-reload
$ systemctl start policyd-rate-guard.service # Start the daemon
$ systemctl enable policyd-rate-guard.service # Enable the daemon to start on boot
$ systemctl enable policyd-rate-guard-cleanup.timer # Enable the cleanup timer
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

> **IMPORTANT:** We strongly recommend the advanced policy client configuration (supported since Postfix 3.0), using above syntax with **default action `DUNNO`**, instead of just using `check_policy_service inet:127.0.0.1:10033`.
>
> It ensures that if RateGuardPolicyd becomes unavailable for any reason, Postfix will ignore it and keep accepting mail as if the rule was not there. RateGuardPolicyd should be considered a "non-critical" policy service and you should use some monitoring solution to ensure it is always running as expected.

> **NOTE:** You may use `unix:rateguard/policyd` instead of `inet:127.0.0.1:10033` if you have configured RateGuardPolicyd to use a unix socket (`SOCKET="/var/spool/postfix/rateguard/policyd"` environment variable).

Make sure to reload Postfix after this change:

```bash
$ systemctl reload postfix
```

## Configuration

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
- `SYSLOG`
  Send logs to syslog. Possible values: `True` or `False`. Defaults to `False`

For production, we recommend to start by copying `.env.example` and then fine-tune your `.env`:

```bash
$ cp .env.example .env
```

## Development

### Initial setup

To set up a basic developer environment, run the following commands:

```bash
$ git clone git@gitlab.onlime.ch:onlime/policyd-rate-guard.git
$ cd policyd-rate-guard
$ python3 -m venv venv
$ . venv/bin/activate
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

To cleanup (reset all counters and quotas) the database, run:

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

> Make sure to always run the tests inside your venv!

### Create DB migrations

In venv, use the [`yoyo new`](https://ollycope.com/software/yoyo/latest/#yoyo-new) command to create a new migration:

```bash
(venv)$ yoyo new --sql -m 'update table ratelimits'
```

The migration will be placed in `database/migrations` directory. After having written the migration statements, apply the migration like this:

```bash
(venv)$ yoyo apply
```

## TODO

Planned features (coming soon):

- [ ] **Sentry** integration for exception reporting
- [ ] Implement a **configurable webhook API** call for notification to sender on reaching quota limit (on first block) to external service.
- [ ] **Ansible role** for easy production deployment

## Credits

**[PolicydRateGuard](https://github.com/onlime/policyd-rate-guard)** is the official successor of [ratelimit-policyd](https://github.com/onlime/ratelimit-policyd) which was running rock-solid for the last 10yrs, but suffered the fact that it was built on a shitty scripting language, formerly known as Perl. We consider the switch to Python a huge step up that will ease further development and make you feel at home.

It was greatly inspired by [policyd-rate-limit](https://github.com/nitmir/policyd-rate-limit) (by [@nitmir](https://github.com/nitmir)). PolicydRateGuard has a different feature-set and a much simpler codebase, but thing like the daemonizing logic were taken from policyd-rate-limit.

## Authors

Created with ❤️ by [Martin Wittwer (Wittwer IT Services)](https://www.wittwer-it.ch/) and [Philip Iezzi (Onlime GmbH)](https://www.onlime.ch/).

## License

This package is licenced under the [GPL-3.0 license](LICENSE) however support is more than welcome.
