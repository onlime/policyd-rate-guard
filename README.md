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

## Running the tests

To run the tests, run the following commands:

```bash
$ docker-compose up -d
$ cp yoyo.ini.example yoyo.ini # & Adjust the settings
$ yoyo apply
$ ./tests.sh
```