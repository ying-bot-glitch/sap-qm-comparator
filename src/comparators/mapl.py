from .base import AbstractComparator


class MaplComparator(AbstractComparator):
    TABLE = "MAPL"
    PRIMARY_KEYS = ["MATNR", "WERKS", "PLNNR", "PLNKN"]
