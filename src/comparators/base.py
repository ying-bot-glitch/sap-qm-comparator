from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd
import yaml


@dataclass
class FieldDiff:
    field_name: str
    comparison_type: str      # direct | mapped | default
    r3_value: Any
    s4_value: Any
    expected_s4_value: Any = None


@dataclass
class DiffResult:
    table: str
    primary_key: dict
    status: str               # MATCH | MISMATCH | MISSING_IN_S4 | NEW_IN_S4 | UNMAPPED_KEY
    field_diffs: List[FieldDiff] = field(default_factory=list)


def load_field_rules(rules_path: str) -> Dict:
    with open(rules_path) as f:
        return yaml.safe_load(f) or {}


def load_mapping_table(mapping_source: str, r3_key: str, s4_key: str) -> Dict:
    """Load a value mapping CSV/Excel into a lookup dict {r3_val: s4_val}."""
    if mapping_source.endswith(".xlsx"):
        df = pd.read_excel(mapping_source, dtype=str)
    else:
        df = pd.read_csv(mapping_source, dtype=str)
    return dict(zip(df[r3_key].str.strip(), df[s4_key].str.strip()))


class AbstractComparator:
    TABLE: str = ""
    PRIMARY_KEYS: List[str] = []

    def __init__(self, field_rules: Dict, key_mapping_df: pd.DataFrame, key_mapping_cfg: Dict):
        self.rules: Dict = field_rules.get(self.TABLE, {})
        self._mapping_cache: Dict[str, Dict] = {}
        self.key_mapping_df = key_mapping_df
        self.km_cfg = key_mapping_cfg

    # ------------------------------------------------------------------ #
    # Key translation                                                       #
    # ------------------------------------------------------------------ #

    def apply_key_mapping(self, r3_df: pd.DataFrame) -> pd.DataFrame:
        """Translate R/3 PLNNR/PLNKN to S/4 equivalents in-place (copy)."""
        if self.key_mapping_df is None or self.key_mapping_df.empty:
            return r3_df.copy()

        cfg = self.km_cfg
        r3_nr, r3_kn = cfg["r3_plnnr_col"], cfg["r3_plnkn_col"]
        s4_nr, s4_kn = cfg["s4_plnnr_col"], cfg["s4_plnkn_col"]

        df = r3_df.copy()
        merged = df.merge(
            self.key_mapping_df.rename(columns={r3_nr: "PLNNR", r3_kn: "PLNKN",
                                                s4_nr: "_S4_PLNNR", s4_kn: "_S4_PLNKN"}),
            on=["PLNNR", "PLNKN"],
            how="left",
        )
        mapped = merged["_S4_PLNNR"].notna()
        merged.loc[mapped, "PLNNR"] = merged.loc[mapped, "_S4_PLNNR"]
        merged.loc[mapped, "PLNKN"] = merged.loc[mapped, "_S4_PLNKN"]
        merged["_unmapped"] = ~mapped
        return merged.drop(columns=["_S4_PLNNR", "_S4_PLNKN"])

    # ------------------------------------------------------------------ #
    # Main comparison                                                       #
    # ------------------------------------------------------------------ #

    def compare(self, r3_df: pd.DataFrame, s4_df: pd.DataFrame) -> List[DiffResult]:
        r3_mapped = self.apply_key_mapping(r3_df)

        unmapped_mask = r3_mapped.get("_unmapped", pd.Series(False, index=r3_mapped.index))
        unmapped_records = r3_mapped[unmapped_mask]
        r3_clean = r3_mapped[~unmapped_mask].drop(columns=["_unmapped"], errors="ignore")

        results: List[DiffResult] = []

        for _, row in unmapped_records.iterrows():
            pk = {k: row.get(k, "") for k in self.PRIMARY_KEYS}
            results.append(DiffResult(table=self.TABLE, primary_key=pk, status="UNMAPPED_KEY"))

        r3_idx = r3_clean.set_index(self.PRIMARY_KEYS)
        s4_idx = s4_df.set_index(self.PRIMARY_KEYS)

        all_r3_keys = set(map(tuple, r3_idx.index.tolist()) if len(self.PRIMARY_KEYS) > 1
                          else [(k,) for k in r3_idx.index.tolist()])
        all_s4_keys = set(map(tuple, s4_idx.index.tolist()) if len(self.PRIMARY_KEYS) > 1
                          else [(k,) for k in s4_idx.index.tolist()])

        for key in all_r3_keys - all_s4_keys:
            pk = dict(zip(self.PRIMARY_KEYS, key))
            results.append(DiffResult(table=self.TABLE, primary_key=pk, status="MISSING_IN_S4"))

        for key in all_s4_keys - all_r3_keys:
            pk = dict(zip(self.PRIMARY_KEYS, key))
            results.append(DiffResult(table=self.TABLE, primary_key=pk, status="NEW_IN_S4"))

        common_keys = all_r3_keys & all_s4_keys
        compare_cols = [c for c in r3_idx.columns if c in s4_idx.columns]

        for key in common_keys:
            idx_key = key[0] if len(key) == 1 else key
            r3_row = r3_idx.loc[idx_key]
            s4_row = s4_idx.loc[idx_key]
            pk = dict(zip(self.PRIMARY_KEYS, key))
            diffs = self._compare_row(r3_row, s4_row, compare_cols)
            status = "MISMATCH" if diffs else "MATCH"
            results.append(DiffResult(table=self.TABLE, primary_key=pk, status=status, field_diffs=diffs))

        return results

    def _compare_row(self, r3_row, s4_row, cols: List[str]) -> List[FieldDiff]:
        diffs = []
        for col in cols:
            rule = self.rules.get(col, {})
            ctype = rule.get("type", "direct") if isinstance(rule, dict) else rule

            if ctype == "ignored":
                continue

            r3_val = str(r3_row.get(col, "") or "").strip()
            s4_val = str(s4_row.get(col, "") or "").strip()

            if ctype == "direct":
                if r3_val != s4_val:
                    diffs.append(FieldDiff(col, "direct", r3_val, s4_val))

            elif ctype == "mapped":
                mapping = self._get_mapping(rule)
                expected = mapping.get(r3_val, r3_val)
                if expected != s4_val:
                    diffs.append(FieldDiff(col, "mapped", r3_val, s4_val, expected))

            elif ctype == "default":
                expected = str(rule.get("expected_value", ""))
                if s4_val != expected:
                    diffs.append(FieldDiff(col, "default", r3_val, s4_val, expected))

        return diffs

    def _get_mapping(self, rule: dict) -> dict:
        src = rule["mapping_source"]
        if src not in self._mapping_cache:
            self._mapping_cache[src] = load_mapping_table(src, rule["r3_key"], rule["s4_key"])
        return self._mapping_cache[src]
