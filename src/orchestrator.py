from __future__ import annotations
import yaml
import pandas as pd
from typing import Callable, Dict, List, Optional, Tuple

from .loaders.file_loader import make_loader
from .loaders.oracle_loader import OracleLoader
from .loaders.base import AbstractLoader
from .comparators.base import DiffResult, load_field_rules
from .comparators.plko import PlkoComparator
from .comparators.plpo import PlpoComparator
from .comparators.plmk import PlmkComparator
from .comparators.mapl import MaplComparator

COMPARATOR_MAP = {
    "PLKO": PlkoComparator,
    "PLPO": PlpoComparator,
    "PLMK": PlmkComparator,
    "MAPL": MaplComparator,
}

_PLPO_KEY_COLS = ["PLNNR", "PLNKN", "PLNFL", "VORNR"]


def load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_scope_cfg(path: str = "config/scope.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _read_file(source: str, sheet: str = "Sheet1") -> pd.DataFrame:
    if source.endswith((".xlsx", ".xls")):
        return pd.read_excel(source, sheet_name=sheet, dtype=str)
    return pd.read_csv(source, dtype=str)


class Orchestrator:
    def __init__(self, settings: dict, scope_cfg: dict):
        self.settings = settings
        self.scope_cfg = scope_cfg

        self.r3_loader: AbstractLoader = make_loader(settings["datasources"]["r3"])
        self.s4_loader: AbstractLoader = make_loader(settings["datasources"]["s4"])

        self.field_rules = self._resolve_field_rules()
        self.km_cfg = settings.get("key_mapping", {})
        self.key_mapping_df: pd.DataFrame = pd.DataFrame()

    @property
    def r3_is_oracle(self) -> bool:
        return isinstance(self.r3_loader, OracleLoader)

    @property
    def s4_is_oracle(self) -> bool:
        return isinstance(self.s4_loader, OracleLoader)

    def _resolve_field_rules(self) -> dict:
        """Load field_rules.yaml and resolve mapping_key references to actual file paths."""
        raw = load_field_rules("config/field_rules.yaml")
        mapping_files = self.settings.get("mapping_files", {})
        resolved: dict = {}
        for table, rules in raw.items():
            resolved[table] = {}
            for field, rule in rules.items():
                if isinstance(rule, dict) and "mapping_key" in rule:
                    key = rule["mapping_key"]
                    mf = mapping_files.get(key, {})
                    if mf.get("source"):
                        resolved[table][field] = {
                            "type": "mapped",
                            "mapping_source": mf["source"],
                            "r3_key": mf.get("r3_key", ""),
                            "s4_key": mf.get("s4_key", ""),
                        }
                    else:
                        resolved[table][field] = {"type": "direct"}
                else:
                    resolved[table][field] = rule
        return resolved

    def load_key_mapping(self):
        if self.km_cfg and self.km_cfg.get("source"):
            self.key_mapping_df = self.r3_loader.load_key_mapping(self.km_cfg)

    def load_scope(self) -> Tuple[List, List, List, List]:
        """Returns (scope_materials, scope_plants, r3_vendors, s4_vendors).
        Called only when at least one side is Oracle.
        """
        mat_cfg = self.scope_cfg.get("scope_materials", {})
        ven_cfg = self.scope_cfg.get("scope_vendors", {})
        plant_filter = self.scope_cfg.get("plant", "")

        scope_materials: List = []
        scope_plants: List = []

        if mat_cfg.get("source"):
            df = _read_file(mat_cfg["source"], mat_cfg.get("sheet", "Sheet1"))
            df.columns = [c.strip().upper() for c in df.columns]
            matnr_col = mat_cfg.get("matnr_column", "MATNR").upper()
            werks_col = mat_cfg.get("werks_column", "WERKS").upper()
            if plant_filter and werks_col in df.columns:
                df = df[df[werks_col].str.strip() == str(plant_filter)]
            if matnr_col in df.columns:
                scope_materials = df[matnr_col].dropna().str.strip().unique().tolist()
            if werks_col in df.columns:
                scope_plants = df[werks_col].dropna().str.strip().unique().tolist()

        loader = self.r3_loader if self.r3_is_oracle else self.s4_loader
        r3_vendors: List = []
        s4_vendors: List = []
        if ven_cfg.get("source"):
            sheet = ven_cfg.get("sheet", "Sheet1")
            r3_vendors = loader.load_scope(ven_cfg["source"], ven_cfg["r3_column"], sheet)
            s4_vendors = loader.load_scope(ven_cfg["source"], ven_cfg["s4_column"], sheet)

        return scope_materials, scope_plants, r3_vendors, s4_vendors

    def run(
        self,
        layers: Optional[List[str]] = None,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ) -> Dict[str, List[DiffResult]]:
        self.load_key_mapping()

        if self.r3_is_oracle or self.s4_is_oracle:
            scope_materials, scope_plants, r3_vendors, s4_vendors = self.load_scope()
        else:
            scope_materials = scope_plants = r3_vendors = s4_vendors = []

        active_layers = layers or list(COMPARATOR_MAP.keys())
        results: Dict[str, List[DiffResult]] = {}

        plko_keys_r3: List = []
        plko_keys_s4: List = []
        plpo_keys_r3: pd.DataFrame = pd.DataFrame()
        plpo_keys_s4: pd.DataFrame = pd.DataFrame()

        for i, layer in enumerate(active_layers):
            if progress_cb:
                progress_cb(layer, i, len(active_layers))

            comparator_cls = COMPARATOR_MAP[layer]
            comparator = comparator_cls(self.field_rules, self.key_mapping_df, self.km_cfg)

            filters_r3: dict = (
                {"scope_materials": scope_materials, "scope_plants": scope_plants, "scope_vendors": r3_vendors}
                if self.r3_is_oracle else {}
            )
            filters_s4: dict = (
                {"scope_materials": scope_materials, "scope_plants": scope_plants, "scope_vendors": s4_vendors}
                if self.s4_is_oracle else {}
            )

            if layer == "PLKO":
                r3_df = self.r3_loader.load_table("plko", filters_r3)
                s4_df = self.s4_loader.load_table("plko", filters_s4)
                plko_keys_r3 = r3_df["PLNNR"].unique().tolist() if "PLNNR" in r3_df.columns else []
                plko_keys_s4 = s4_df["PLNNR"].unique().tolist() if "PLNNR" in s4_df.columns else []

            elif layer == "PLPO":
                if plko_keys_r3:
                    filters_r3["plko_keys"] = plko_keys_r3
                if plko_keys_s4:
                    filters_s4["plko_keys"] = plko_keys_s4
                r3_df = self.r3_loader.load_table("plpo", filters_r3)
                s4_df = self.s4_loader.load_table("plpo", filters_s4)
                if self.r3_is_oracle and all(c in r3_df.columns for c in _PLPO_KEY_COLS):
                    plpo_keys_r3 = r3_df[_PLPO_KEY_COLS].drop_duplicates()
                if self.s4_is_oracle and all(c in s4_df.columns for c in _PLPO_KEY_COLS):
                    plpo_keys_s4 = s4_df[_PLPO_KEY_COLS].drop_duplicates()

            elif layer == "PLMK":
                if plko_keys_r3:
                    filters_r3["plko_keys"] = plko_keys_r3
                if plko_keys_s4:
                    filters_s4["plko_keys"] = plko_keys_s4
                r3_df = self.r3_loader.load_table("plmk", filters_r3)
                s4_df = self.s4_loader.load_table("plmk", filters_s4)
                # Post-filter by valid operations from PLPO result (Oracle only)
                if self.r3_is_oracle and not plpo_keys_r3.empty and not r3_df.empty:
                    if all(c in r3_df.columns for c in _PLPO_KEY_COLS):
                        r3_df = r3_df.merge(plpo_keys_r3, on=_PLPO_KEY_COLS, how="inner")
                if self.s4_is_oracle and not plpo_keys_s4.empty and not s4_df.empty:
                    if all(c in s4_df.columns for c in _PLPO_KEY_COLS):
                        s4_df = s4_df.merge(plpo_keys_s4, on=_PLPO_KEY_COLS, how="inner")

            else:  # MAPL
                if plko_keys_r3:
                    filters_r3["plko_keys"] = plko_keys_r3
                if plko_keys_s4:
                    filters_s4["plko_keys"] = plko_keys_s4
                r3_df = self.r3_loader.load_table("mapl", filters_r3)
                s4_df = self.s4_loader.load_table("mapl", filters_s4)

            layer_results = comparator.compare(r3_df, s4_df)
            results[layer] = layer_results

        if progress_cb:
            progress_cb("Done", len(active_layers), len(active_layers))

        return results


def summarise(results: Dict[str, List[DiffResult]]) -> pd.DataFrame:
    rows = []
    for table, diffs in results.items():
        counts: dict = {"MATCH": 0, "MISMATCH": 0, "MISSING_IN_S4": 0, "NEW_IN_S4": 0, "UNMAPPED_KEY": 0}
        for d in diffs:
            counts[d.status] = counts.get(d.status, 0) + 1
        total = sum(counts.values())
        match_rate = round(counts["MATCH"] / total * 100, 1) if total else 0
        rows.append({"Table": table, "Total": total, **counts, "Match Rate %": match_rate})
    return pd.DataFrame(rows)
