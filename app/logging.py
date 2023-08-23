import logging
import logging.handlers

def get_logger(conf):
    """Get logger"""
    logger = logging.getLogger('policyd-rate-guard')
    logger.setLevel(getattr(logging, conf.get('LOG_LEVEL', 'INFO').upper(), logging.INFO))
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    if conf.get('SYSLOG', 'False').lower() in ('true', 'yes', '1'):
        syslog = logging.handlers.SysLogHandler(address='/dev/log')
        # TODO: Make facility configurable
        syslog.setFormatter(formatter)
        logger.addHandler(syslog)
    else:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    return logger
