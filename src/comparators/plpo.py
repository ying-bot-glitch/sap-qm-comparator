from .base import AbstractComparator


class PlpoComparator(AbstractComparator):
    TABLE = "PLPO"
    PRIMARY_KEYS = ["PLNNR", "PLNKN", "PLNFL", "VORNR"]
