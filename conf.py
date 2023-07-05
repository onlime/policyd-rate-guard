from os import getenv
from dotenv import load_dotenv


class Config:
    def __init__(self) -> None:
        load_dotenv()

    def get(self, key: str, default: object = None) -> str:
        return getenv(key, default)
