from os import getenv
from dotenv import load_dotenv


class Config:
    def __init__(self, path = None) -> None:
        load_dotenv(dotenv_path=path)

    def get(self, key: str, default: object = None) -> str:
        return getenv(key, default)

    def get_array(self, key: str, default: list = []) -> list:
        return getenv(key, default).split(',')