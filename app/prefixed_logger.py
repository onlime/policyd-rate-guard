import inspect
import logging
from os import path

class PrefixedLogger(logging.Logger):
    """Custom logger that prefixes messages with msgid, the filename, class and function name of the caller"""

    msg_prefix = True
    msgid = None

    def __init__(self, name, level=logging.NOTSET):
        super().__init__(name, level)

    def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False):
        if self.msg_prefix:
            co_filename, co_class, co_function = self._get_caller_info()
            prefix = f"{path.basename(co_filename)} {co_class}.{co_function}() - "
        else:
            prefix = ''
        if self.msgid:
            prefix += f"{self.msgid}: "
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
