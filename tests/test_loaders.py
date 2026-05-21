import pytest
import pandas as pd
import os
from src.loaders.base import AbstractLoader
from src.loaders.file_loader import FileLoader, make_loader, FILE_TABLES
from src.loaders.oracle_loader import build_table_name


# ------------------------------------------------------------------ #
# build_table_name                                                     #
# ------------------------------------------------------------------ #

def test_build_table_name_format():
    assert build_table_name("mard_qmap_vert_sys", "plko", "poe") == \
           "mard_qmap_vert_sys.v_rep_qmap_vert_sys_plko_poe"


def test_build_table_name_lowercase():
    assert build_table_name("MARD_QMAP_VERT_SYS", "PLKO", "POE") == \
           "mard_qmap_vert_sys.v_rep_qmap_vert_sys_plko_poe"


def test_build_table_name_s4_machine():
    assert build_table_name("mard_qmap_vert_sys", "plmk", "s4p") == \
           "mard_qmap_vert_sys.v_rep_qmap_vert_sys_plmk_s4p"


def test_file_tables_no_plmw():
    assert "plmw" not in FILE_TABLES
    assert "plas" not in FILE_TABLES
    assert set(FILE_TABLES) == {"plko", "plpo", "plmk", "mapl"}


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

@pytest.fixture
def csv_plko(tmp_path):
    df = pd.DataFrame({
        "PLNNR": ["100", "200"],
        "PLNKN": ["1", "1"],
        "WERKS": ["1000", "1000"],
        "VERWE": ["5", "5"],
        "STATU": ["4", "4"],
        "LOEKZ": ["", ""],
    })
    path = tmp_path / "plko.csv"
    df.to_csv(path, index=False)
    return str(path)


@pytest.fixture
def csv_file_mapping(csv_plko, tmp_path):
    """A file_mapping dict with only plko populated."""
    return {"plko": csv_plko, "plpo": "", "plmk": "", "mapl": ""}


# ------------------------------------------------------------------ #
# FileLoader — CSV                                                     #
# ------------------------------------------------------------------ #

def test_file_loader_csv_loads(csv_file_mapping):
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    df = loader.load_table("plko")
    assert len(df) == 2
    assert "PLNNR" in df.columns


def test_file_loader_csv_filter_verwe(csv_file_mapping):
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    df = loader.load_table("plko", filters={})
    assert all(df["VERWE"] == "5")


def test_file_loader_missing_table_returns_empty(csv_file_mapping):
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    df = loader.load_table("mapl")   # no path configured
    assert df.empty


def test_file_loader_test_connection_ok(csv_file_mapping):
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    ok, _ = loader.test_connection()
    assert ok


def test_file_loader_test_connection_missing():
    loader = FileLoader({"type": "csv", "file_mapping": {"plko": "/nonexistent/plko.csv"}})
    ok, msg = loader.test_connection()
    assert not ok
    assert "plko" in msg


def test_file_loader_no_mapping():
    loader = FileLoader({"type": "csv", "file_mapping": {}})
    ok, msg = loader.test_connection()
    assert not ok


# ------------------------------------------------------------------ #
# FileLoader — Excel                                                   #
# ------------------------------------------------------------------ #

@pytest.fixture
def excel_plko(tmp_path):
    df = pd.DataFrame({
        "PLNNR": ["300"],
        "PLNKN": ["1"],
        "WERKS": ["2000"],
        "VERWE": ["5"],
        "STATU": ["4"],
        "LOEKZ": [""],
    })
    path = tmp_path / "plko.xlsx"
    df.to_excel(path, index=False)
    return str(path)


def test_file_loader_excel_loads(excel_plko):
    loader = FileLoader({"type": "excel", "file_mapping": {"plko": excel_plko}})
    df = loader.load_table("plko")
    assert len(df) == 1
    assert df.iloc[0]["PLNNR"] == "300"


# ------------------------------------------------------------------ #
# Scope loading                                                        #
# ------------------------------------------------------------------ #

@pytest.fixture
def scope_csv(tmp_path):
    df = pd.DataFrame({"MATNR": ["MAT001", "MAT002", " MAT003 "]})
    path = tmp_path / "scope.csv"
    df.to_csv(path, index=False)
    return str(path)


def test_load_scope_csv_strips(csv_file_mapping, scope_csv):
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    materials = loader.load_scope(scope_csv, "MATNR")
    assert "MAT003" in materials
    assert len(materials) == 3


# ------------------------------------------------------------------ #
# Key mapping loading                                                  #
# ------------------------------------------------------------------ #

@pytest.fixture
def key_mapping_csv(tmp_path):
    df = pd.DataFrame({
        "R3_PLNNR": ["100", "200"],
        "R3_PLNKN": ["1", "1"],
        "S4_PLNNR": ["1000", "2000"],
        "S4_PLNKN": ["1", "1"],
    })
    path = tmp_path / "mapping.csv"
    df.to_csv(path, index=False)
    return str(path)


def test_load_key_mapping(csv_file_mapping, key_mapping_csv):
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    cfg = {
        "source": key_mapping_csv,
        "r3_plnnr_col": "R3_PLNNR",
        "r3_plnkn_col": "R3_PLNKN",
        "s4_plnnr_col": "S4_PLNNR",
        "s4_plnkn_col": "S4_PLNKN",
    }
    km = loader.load_key_mapping(cfg)
    assert len(km) == 2
    assert "S4_PLNNR" in km.columns


def test_load_key_mapping_missing_column(csv_file_mapping, tmp_path):
    bad_df = pd.DataFrame({"R3_PLNNR": ["100"], "R3_PLNKN": ["1"]})
    bad_path = tmp_path / "bad.csv"
    bad_df.to_csv(bad_path, index=False)
    loader = FileLoader({"type": "csv", "file_mapping": csv_file_mapping})
    cfg = {"source": str(bad_path), "r3_plnnr_col": "R3_PLNNR", "r3_plnkn_col": "R3_PLNKN",
           "s4_plnnr_col": "S4_PLNNR", "s4_plnkn_col": "S4_PLNKN"}
    with pytest.raises(ValueError, match="missing columns"):
        loader.load_key_mapping(cfg)


# ------------------------------------------------------------------ #
# make_loader factory                                                  #
# ------------------------------------------------------------------ #

def test_make_loader_returns_file_loader_csv():
    loader = make_loader({"type": "csv", "file_mapping": {}})
    assert isinstance(loader, FileLoader)


def test_make_loader_returns_file_loader_excel():
    loader = make_loader({"type": "excel", "file_mapping": {}})
    assert isinstance(loader, FileLoader)
