from .base import AbstractComparator


class PlkoComparator(AbstractComparator):
    TABLE = "PLKO"
    PRIMARY_KEYS = ["PLNNR", "PLNKN", "WERKS"]
