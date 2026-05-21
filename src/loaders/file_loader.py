from __future__ import annotations
from typing import Dict, List, Optional
import os
import pandas as pd
from .base import AbstractLoader

FILE_TABLES: List[str] = ["plko", "plpo", "plmk", "mapl"]


class FileLoader(AbstractLoader):
    """Loads SAP QM data from Excel or CSV — one file per SAP table."""

    def __init__(self, config: dict):
        self.file_type = config["type"]                        # 'excel' | 'csv'
        self.file_mapping: Dict[str, str] = config.get("file_mapping", {})

    def test_connection(self) -> tuple[bool, str]:
        missing = [t for t, p in self.file_mapping.items() if p and not os.path.exists(p)]
        if missing:
            return False, f"Files not found for: {', '.join(missing)}"
        if not self.file_mapping:
            return False, "No files configured"
        return True, "All files accessible"

    def load_table(self, sap_table: str, filters: Optional[Dict] = None) -> pd.DataFrame:
        path = self.file_mapping.get(sap_table.lower(), "")
        if not path or not os.path.exists(path):
            return pd.DataFrame()

        if self.file_type == "excel":
            df = pd.read_excel(path, dtype=str)
        else:
            df = pd.read_csv(path, dtype=str)

        df.columns = [c.upper() for c in df.columns]
        df = df.fillna("")
        if filters:
            df = self._apply_filters(df, sap_table.lower(), filters)
        return df

    def _apply_filters(self, df: pd.DataFrame, sap_table: str, filters: dict) -> pd.DataFrame:
        if "LOEKZ" in df.columns:
            df = df[df["LOEKZ"].isin(["", None]) | df["LOEKZ"].isna()]
        if sap_table == "plko":
            if "VERWE" in df.columns:
                df = df[df["VERWE"] == "5"]
            if "STATU" in df.columns:
                df = df[df["STATU"] != "7"]
        if "plko_keys" in filters and "PLNNR" in df.columns:
            df = df[df["PLNNR"].isin(filters["plko_keys"])]
        if "scope_materials" in filters and "MATNR" in df.columns:
            df = df[df["MATNR"].isin(filters["scope_materials"])]
        if "scope_plants" in filters and "WERKS" in df.columns:
            df = df[df["WERKS"].isin(filters["scope_plants"])]
        return df.reset_index(drop=True)


def make_loader(config: dict) -> AbstractLoader:
    from .oracle_loader import OracleLoader
    if config.get("type", "oracle") == "oracle":
        return OracleLoader(config)
    return FileLoader(config)
