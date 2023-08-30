import inspect
import logging
import logging.handlers
from app.conf import Config
from os import path

class PrefixedLogger(logging.Logger):
    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False):
        co_filename, co_class, co_function = self._get_caller_info()
        prefix = f"{path.basename(co_filename)} {co_class}.{co_function}() - "
        msg = prefix + msg
        super()._log(level, msg, args, exc_info, extra, stack_info)

    def _get_caller_info(self):
        frame = self._get_caller_frame()
        co_filename = frame.f_code.co_filename
        co_class = frame.f_locals.get('self', None).__class__.__name__ if 'self' in frame.f_locals else None
        co_function = frame.f_code.co_name
        return co_filename, co_class, co_function
    
    def _get_caller_frame(self):
        frame = inspect.currentframe().f_back
        try:
            # Traverse back the call stack to find the first caller frame outside this logger class (usually 3 steps back)
            # while frame and self.__class__ in frame.f_locals.get('__class__', ()):
            while frame and self.__class__.__name__ == frame.f_locals.get('self', None).__class__.__name__:
                frame = frame.f_back
        except (AttributeError):
            pass # Ignore AttributeError: 'NoneType' object has no attribute '__class__'
        return frame

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
    if conf.get('LOG_MSG_PREFIX', True):
        logging.setLoggerClass(PrefixedLogger)
    logging.basicConfig(level=log_level, format=log_format, handlers=log_handlers)
    logger = logging.getLogger('policyd-rate-guard')
    logger.setLevel(log_level)

    return logger
