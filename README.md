# PolicydRateGuard

A slick sender rate limit policy daemon for Postfix, written in Python.

by [Onlime GmbH](https://www.onlime.ch/) – Your Swiss webhosting provider living the "no BS" philosophy! 

## :fire: Announcement 2023-08-28

This project is going to be the successor of [ratelimit-policyd](https://github.com/onlime/ratelimit-policyd). **PolicydRateGuard** is a complete rewrite in Python which is currently under development in a pre-alpha state. It's not ready to be launched yet, but stay tuned!

We're going to release it by the end of summer, hopefully by the end of Sept 2023.

Until then, enjoy the heat and go for a swim.

## Credits

**[PolicydRateGuard](https://github.com/onlime/policyd-rate-guard)** is the official successor of [ratelimit-policyd](https://github.com/onlime/ratelimit-policyd) which was running rock-solid for the last 10yrs, but suffered the fact that it was built on a shitty scripting language, formerly known as Perl. We consider the switch to Python a huge step up that will ease further development and make you feel at home.

It was greatly inspired by [policyd-rate-limit](https://github.com/nitmir/policyd-rate-limit) (by [@nitmir](https://github.com/nitmir)). PolicydRateGuard has a different feature-set and a much simpler codebase, but thing like the daemonizing logic were taken from policyd-rate-limit.

## Authors

Created with ❤️ by [Martin Wittwer (Wittwer IT Services)](https://www.wittwer-it.ch/) and [Philip Iezzi (Onlime GmbH)](https://www.onlime.ch/).

## License

This package is licenced under the [GPL-3.0 license](LICENSE) however support is more than welcome.