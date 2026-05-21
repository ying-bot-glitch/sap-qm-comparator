from .base import AbstractComparator


class PlmkComparator(AbstractComparator):
    TABLE = "PLMK"
    PRIMARY_KEYS = ["PLNNR", "PLNKN", "VORNR", "MERKNR"]
