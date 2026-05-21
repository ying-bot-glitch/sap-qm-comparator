from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import pandas as pd


class AbstractLoader(ABC):
    """Base interface for all data source loaders."""

    @abstractmethod
    def load_table(self, sap_table: str, filters: Optional[Dict] = None) -> pd.DataFrame:
        """Load a SAP table into a DataFrame.

        Args:
            sap_table: lowercase SAP table name, e.g. 'plko'
            filters: optional dict of bind parameters passed to the query
        """

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """Return (success, message)."""

    def load_scope(self, source: str, column: str, sheet: str = "Sheet1") -> List[str]:
        """Load a scope list (materials or vendors) from CSV or Excel."""
        if source.endswith(".xlsx") or source.endswith(".xls"):
            df = pd.read_excel(source, sheet_name=sheet, dtype=str)
        else:
            df = pd.read_csv(source, dtype=str)
        return df[column].dropna().str.strip().tolist()

    def load_key_mapping(self, cfg: dict) -> pd.DataFrame:
        """Load PLNNR/PLNKN mapping from preload/postload file."""
        source = cfg["source"]
        if source.endswith(".xlsx") or source.endswith(".xls"):
            df = pd.read_excel(source, sheet_name=cfg.get("sheet", "Sheet1"), dtype=str)
        else:
            df = pd.read_csv(source, dtype=str)
        required = [cfg["r3_plnnr_col"], cfg["r3_plnkn_col"], cfg["s4_plnnr_col"], cfg["s4_plnkn_col"]]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Key mapping file missing columns: {missing}")
        return df[required].dropna().reset_index(drop=True)
