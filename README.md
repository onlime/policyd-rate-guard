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
