import logging
import logging.handlers
from .conf import Config
from .prefixed_logger import PrefixedLogger

def get_logger(conf: Config):
    """Get logger"""
    log_level = getattr(logging, conf.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)
    log_format = '%(asctime)s %(levelname)s %(message)s'
    log_handlers = []

    log_file = conf.get('LOG_FILE')
    if log_file:
        file = logging.FileHandler(filename=log_file)
        # file.setFormatter(logging.Formatter(log_format))
        log_handlers.append(file)

    if conf.get('LOG_CONSOLE', False):
        console = logging.StreamHandler()
        # console.setFormatter(logging.Formatter(log_format))
        log_handlers.append(console)

    if conf.get('SYSLOG', False):
        syslog = logging.handlers.SysLogHandler(
            # workaround for Docker container: address=('localhost', 514),
            address='/dev/log',
            facility=logging.handlers.SysLogHandler.LOG_MAIL,
        )
        log_format_syslog = '%(name)s[%(process)d]: %(levelname)s %(message)s'
        syslog.setFormatter(logging.Formatter(log_format_syslog))
        log_handlers.append(syslog)

    # Set the custom logger class
    logging.setLoggerClass(PrefixedLogger)
    logging.basicConfig(level=log_level, format=log_format, handlers=log_handlers)
    logger = logging.getLogger('policyd-rate-guard')
    logger.setLevel(log_level)
    logger.msg_prefix = conf.get('LOG_MSG_PREFIX', True) # Enable/disable custom log message prefix feature

    return logger
