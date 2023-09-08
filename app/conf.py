from os import getenv
from dotenv import load_dotenv
from distutils.util import strtobool
from typing import Any


class Config:
    def __init__(self, path: str = None) -> None:
        load_dotenv(dotenv_path=path)

    def get(self, key: str, default: Any = None) -> str:
        value = getenv(key, default)
        if type(default) is bool and type(value) is not bool:
            return bool(strtobool(value))
        else:
            return value

    def get_array(self, key: str, default: Any = None) -> list:
        return getenv(key, default).split(',')
