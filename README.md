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
(venv)$ docker-compose up -d
(venv)$ cp .env.example .env
(venv)$ cp yoyo.ini.example yoyo.ini
(venv)$ yoyo apply
```

## Running the daemon

### Local

To run the daemon, run the following commands:

If needed start the testing DB:

```bash
$ docker-compose up -d
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
$ docker-compose stop db
```

2. Then run the daemon:

```bash
$ docker-compose build
$ docker-compose up -d
```

3. With a SMTP client connect to `localhost:1025` with user `test01@example.com` and password `Example1234` and send some mails.


## Running the tests

To run the tests, run the following commands:

```bash
$ docker-compose up -d
$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
$ yoyo apply
$ ./tests.sh
```