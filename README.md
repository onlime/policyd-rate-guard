# PolicydRateGuard

## Production Install

### Prerequisites

You need a running MySQL/MariaDB server and a running Postfix server with SASL auth to use this daemon.

### Setup

To run the daemon in production, follow this:

1. Prepare MySQL database `policyd-rate-guard` and user `policyd-rate-guard`:

```sql
mysql> CREATE USER `policyd-rate-guard`@localhost IDENTIFIED BY 'Pa55w0rd';
mysql> GRANT ALL ON `policyd-rate-guard`.* TO `policyd-rate-guard`@localhost;
```

2. Copy/clone project to server (we assume `/opt/policyd-rate-guard`)

```bash
$ cd /opt
$ git clone https://gitlab.onlime.ch/onlime/policyd-rate-guard.git
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

We recommend to integrate PolicydRateGuard directly into Postfix using the [`check_policy_service`](https://www.postfix.org/postconf.5.html#check_policy_service) restriction in [`smtpd_data_restrictions`](https://www.postfix.org/postconf.5.html#smtpd_data_restrictions):

```ini
smtpd_data_restrictions =
        reject_unauth_pipelining,
        check_policy_service inet:127.0.0.1:10033,
        permit 
```

Make sure to reload Postfix after this change:

```bash
$ systemctl reload postfix
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

