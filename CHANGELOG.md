# CHANGELOG

## [v0.5.1](https://github.com/onlime/policyd-rate-guard/releases/tag/v0.5.1) (2023-08-30)

**Added:**

- Added `LOG_MSG_PREFIX` (boolean) environment variable which is enabled by default. Prefix all log messages with a prefix containing information about the calling filename, class, and function name, e.g. `ratelimit.py Ratelimit.update() - `. 

**Fixed:**

- Fix `AttributeError: 'NoneType' object has no attribute 'read' in Ratelimit.find()` edge case where `sasl_username` was set in Postfix DATA but empty. We now bail out early if `sasl_username` either does not exist or is empty.

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