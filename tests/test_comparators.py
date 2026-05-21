import pytest
import pandas as pd
from src.comparators.base import AbstractComparator, FieldDiff, DiffResult
from src.comparators.plko import PlkoComparator
from src.comparators.plpo import PlpoComparator
from src.comparators.mapl import MaplComparator


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def make_km_df(r3_nr, r3_kn, s4_nr, s4_kn):
    return pd.DataFrame({
        "R3_PLNNR": [r3_nr], "R3_PLNKN": [r3_kn],
        "S4_PLNNR": [s4_nr], "S4_PLNKN": [s4_kn],
    })

KM_CFG = {
    "r3_plnnr_col": "R3_PLNNR", "r3_plnkn_col": "R3_PLNKN",
    "s4_plnnr_col": "S4_PLNNR", "s4_plnkn_col": "S4_PLNKN",
}

def plko_row(**kwargs):
    base = {"PLNNR": "100", "PLNKN": "1", "WERKS": "1000",
            "VERWE": "5", "STATU": "4", "PLNBEZ": "IP-001"}
    base.update(kwargs)
    return pd.DataFrame([base])


# ------------------------------------------------------------------ #
# Key mapping application                                              #
# ------------------------------------------------------------------ #

def test_apply_key_mapping_translates():
    km = make_km_df("100", "1", "1000", "1")
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1")
    result = comp.apply_key_mapping(r3)
    assert result.iloc[0]["PLNNR"] == "1000"
    assert not result.iloc[0]["_unmapped"]


def test_apply_key_mapping_flags_missing():
    km = make_km_df("999", "1", "9990", "1")
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1")
    result = comp.apply_key_mapping(r3)
    assert result.iloc[0]["_unmapped"]


def test_apply_key_mapping_empty_km_passthrough():
    comp = PlkoComparator({}, pd.DataFrame(), KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1")
    result = comp.apply_key_mapping(r3)
    assert result.iloc[0]["PLNNR"] == "100"


# ------------------------------------------------------------------ #
# MATCH                                                                #
# ------------------------------------------------------------------ #

def test_compare_match():
    km = make_km_df("100", "1", "100", "1")   # same key (no migration shift)
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1", PLNBEZ="IP-001")
    s4 = plko_row(PLNNR="100", PLNKN="1", PLNBEZ="IP-001")
    results = comp.compare(r3, s4)
    assert len(results) == 1
    assert results[0].status == "MATCH"


# ------------------------------------------------------------------ #
# MISMATCH                                                             #
# ------------------------------------------------------------------ #

def test_compare_mismatch_direct_field():
    km = make_km_df("100", "1", "100", "1")
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1", PLNBEZ="IP-001")
    s4 = plko_row(PLNNR="100", PLNKN="1", PLNBEZ="IP-CHANGED")
    results = comp.compare(r3, s4)
    assert results[0].status == "MISMATCH"
    assert any(fd.field_name == "PLNBEZ" for fd in results[0].field_diffs)


def test_compare_mismatch_captures_values():
    km = make_km_df("100", "1", "100", "1")
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1", PLNBEZ="OLD")
    s4 = plko_row(PLNNR="100", PLNKN="1", PLNBEZ="NEW")
    results = comp.compare(r3, s4)
    fd = results[0].field_diffs[0]
    assert fd.r3_value == "OLD"
    assert fd.s4_value == "NEW"


# ------------------------------------------------------------------ #
# MISSING_IN_S4 / NEW_IN_S4                                           #
# ------------------------------------------------------------------ #

def test_compare_missing_in_s4():
    km = make_km_df("100", "1", "100", "1")
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1")
    s4 = pd.DataFrame(columns=r3.columns)
    results = comp.compare(r3, s4)
    assert results[0].status == "MISSING_IN_S4"


def test_compare_new_in_s4():
    km = pd.DataFrame(columns=["R3_PLNNR", "R3_PLNKN", "S4_PLNNR", "S4_PLNKN"])
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = pd.DataFrame(columns=plko_row().columns)
    s4 = plko_row(PLNNR="999", PLNKN="1")
    results = comp.compare(r3, s4)
    assert results[0].status == "NEW_IN_S4"


# ------------------------------------------------------------------ #
# UNMAPPED_KEY                                                         #
# ------------------------------------------------------------------ #

def test_compare_unmapped_key():
    km = make_km_df("999", "1", "9990", "1")   # mapping for 999, not 100
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1")
    s4 = pd.DataFrame(columns=r3.columns)
    results = comp.compare(r3, s4)
    statuses = {r.status for r in results}
    assert "UNMAPPED_KEY" in statuses


# ------------------------------------------------------------------ #
# Field rules — ignored fields                                         #
# ------------------------------------------------------------------ #

def test_ignored_fields_not_reported():
    km = make_km_df("100", "1", "100", "1")
    rules = {"PLKO": {"ERDAT": {"type": "ignored"}}}
    comp = PlkoComparator(rules, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1", ERDAT="20240101")
    s4 = plko_row(PLNNR="100", PLNKN="1", ERDAT="20250101")
    results = comp.compare(r3, s4)
    assert results[0].status == "MATCH"
    assert not any(fd.field_name == "ERDAT" for fd in results[0].field_diffs)


# ------------------------------------------------------------------ #
# Field rules — default type                                           #
# ------------------------------------------------------------------ #

def test_default_field_mismatch():
    km = make_km_df("100", "1", "100", "1")
    rules = {"PLKO": {"NEW_S4_FIELD": {"type": "default", "expected_value": "01"}}}
    comp = PlkoComparator(rules, km, KM_CFG)
    r3 = plko_row(PLNNR="100", PLNKN="1", NEW_S4_FIELD="")
    s4 = plko_row(PLNNR="100", PLNKN="1", NEW_S4_FIELD="99")
    results = comp.compare(r3, s4)
    assert results[0].status == "MISMATCH"
    fd = next(f for f in results[0].field_diffs if f.field_name == "NEW_S4_FIELD")
    assert fd.expected_s4_value == "01"


# ------------------------------------------------------------------ #
# Multi-key comparators                                                #
# ------------------------------------------------------------------ #

def test_plpo_primary_keys():
    assert PlpoComparator.PRIMARY_KEYS == ["PLNNR", "PLNKN", "PLNFL", "VORNR"]


def test_mapl_primary_keys():
    assert MaplComparator.PRIMARY_KEYS == ["MATNR", "WERKS", "PLNNR", "PLNKN"]


# ------------------------------------------------------------------ #
# Multiple records                                                     #
# ------------------------------------------------------------------ #

def test_compare_multiple_records_mixed():
    km = pd.DataFrame({
        "R3_PLNNR": ["100", "200", "300"],
        "R3_PLNKN": ["1", "1", "1"],
        "S4_PLNNR": ["100", "200", "300"],
        "S4_PLNKN": ["1", "1", "1"],
    })
    comp = PlkoComparator({}, km, KM_CFG)
    r3 = pd.DataFrame([
        {"PLNNR": "100", "PLNKN": "1", "WERKS": "1000", "VERWE": "5", "STATU": "4", "PLNBEZ": "A"},
        {"PLNNR": "200", "PLNKN": "1", "WERKS": "1000", "VERWE": "5", "STATU": "4", "PLNBEZ": "B"},
        {"PLNNR": "300", "PLNKN": "1", "WERKS": "1000", "VERWE": "5", "STATU": "4", "PLNBEZ": "C"},
    ])
    s4 = pd.DataFrame([
        {"PLNNR": "100", "PLNKN": "1", "WERKS": "1000", "VERWE": "5", "STATU": "4", "PLNBEZ": "A"},
        {"PLNNR": "200", "PLNKN": "1", "WERKS": "1000", "VERWE": "5", "STATU": "4", "PLNBEZ": "B_CHANGED"},
    ])
    results = comp.compare(r3, s4)
    by_status = {r.status for r in results}
    assert "MATCH" in by_status
    assert "MISMATCH" in by_status
    assert "MISSING_IN_S4" in by_status
