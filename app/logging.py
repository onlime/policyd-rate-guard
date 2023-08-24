import logging
import logging.handlers
from app.conf import Config

def get_logger(conf: Config):
    """Get logger"""
    logger = logging.getLogger('policyd-rate-guard')
    logger.setLevel(getattr(logging, conf.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
    if conf.get('SYSLOG', False):
        formatter = logging.Formatter('%(name)s %(levelname)s %(message)s')
        syslog = logging.handlers.SysLogHandler(
            # workaround for Docker container: address=('localhost', 514),
            address='/dev/log',
            facility=logging.handlers.SysLogHandler.LOG_MAIL,
        )
        syslog.setFormatter(formatter)
        logger.addHandler(syslog)
    else:
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    return logger
