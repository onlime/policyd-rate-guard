# PolicydRateGuard

## Initial setup

To set up a basic developer environment, run the following commands:

```bash
$ git clone git@gitlab.onlime.ch:onlime/policyd-rate-guard.git
$ cd policyd-rate-guard
$ python3 -m venv venv
$ source venv/bin/activate
(venv)$ pip install --upgrade pip
(venv)$ pip install -r requirements.txt
(venv)$ docker-compose up -d db
(venv)$ cp .env.example .env
(venv)$ cp yoyo.ini.example yoyo.ini
(venv)$ yoyo apply
```

## Running the daemon

### Local

To run the daemon, run the following commands:

If needed start the testing DB:

```bash
$ docker-compose up -d db
```

Then run the daemon:

```bash
$ cp .env.example .env # & Adjust the settings
$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
$ yoyo apply
$ python3 run.py
```

### Docker

To run a full test environment with a postfix with SASL auth and a policyd-rate-guard daemon, run the following commands:

1. You have to seed the database before running the daemon. This is done like that:

```bash
$ docker-compose up -d db
$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
$ yoyo apply
$ docker-compose stop db # if needed
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

### Production

#### Prerequisites

You need a running MySQL/MariaDB server and a running Postfix server with SASL auth to use this daemon.

#### Setup

To run the daemon in production, follow this:

1. Copy/clone project to server (we assume `/opt/policyd-rate-guard`)

2. Create a virtualenv and install the requirements:

```bash
$ cd /opt/policyd-rate-guard
$ python3 -m venv venv
$ source venv/bin/activate
(venv)$ pip install --upgrade pip
(venv)$ pip install -r requirements.txt
(venv)$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
(venv)$ yoyo apply # Run the database migrations
(venv)$ cp .env.example .env # & Adjust the settings
```

3. Copy the systemd service files to `/etc/systemd/system/` and adjust the settings:

```bash
$ cp deployment/systemd_daemon.service /etc/systemd/system/policyd-rate-guard.service # & Adjust the settings
$ cp deployment/systemd_cleanup.service /etc/systemd/system/policyd-rate-guard-cleanup.service # & Adjust the settings
$ cp deployment/systemd_cleanup.timer /etc/systemd/system/policyd-rate-guard-cleanup.timer # & Adjust the settings
```

4. Enable and start the services:

```bash
$ systemctl daemon-reload
$ systemctl start policyd-rate-guard.service # Start the daemon
$ systemctl enable policyd-rate-guard.service # Enable the daemon to start on boot
$ systemctl enable policyd-rate-guard-cleanup.timer # Enable the cleanup timer
```

## Running the tests

To run the tests, run the following commands:

```bash
$ docker-compose up -d db
$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
$ yoyo apply
$ ./tests.sh
```
