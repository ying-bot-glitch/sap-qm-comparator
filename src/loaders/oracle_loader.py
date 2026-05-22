from __future__ import annotations
import os
import re
from typing import Dict, List, Optional, Tuple
import pandas as pd
import oracledb
from .base import AbstractLoader

SERVICE_OPTIONS = [
    "REDLake_ZeusP_Consumer_DALI.world",
    "REDLake_ZeusQ_Consumer_DALI.world",
]

_oracle_client_initialized = False


def build_table_name(schema: str, sap_table: str, sap_machine: str) -> str:
    return f"{schema}.v_rep_qmap_vert_sys_{sap_table}_{sap_machine}".lower()


def _in_clause(col: str, values: list) -> str:
    """Build an Oracle-safe IN clause, splitting into ≤999-item chunks."""
    if not values:
        return ""
    escaped = [f"'{str(v).replace(chr(39), chr(39)+chr(39))}'" for v in values]
    chunks = [escaped[i:i + 999] for i in range(0, len(escaped), 999)]
    if len(chunks) == 1:
        return f"{col} IN ({', '.join(chunks[0])})"
    parts = [f"{col} IN ({', '.join(chunk)})" for chunk in chunks]
    return f"({' OR '.join(parts)})"


class OracleLoader(AbstractLoader):
    """Loads SAP QM data from Oracle via thin mode (host:port/service)
    or thick mode (TNS alias via Oracle Instant Client)."""

    SAP_TABLES = ["plko", "plpo", "plmk", "mapl", "plas"]

    def __init__(self, config: dict):
        self.service = config["service"]
        self.host = config.get("host", "")
        self.port = int(config.get("port", 1521) or 1521)
        self.user = config["user"]
        self.password = config["password"]
        self.schema = config["schema"]
        self.sap_machine = config["sap_machine"]

    def _connect(self):
        global _oracle_client_initialized

        # If service looks like a TNS alias (no dots/colons/slashes) OR no host given → thick mode
        is_tns_alias = (
            bool(self.service)
            and not re.search(r'[\./:]', self.service)
            and not re.match(r'\d+\.\d+', self.service)
        )

        if is_tns_alias or not self.host:
            if not _oracle_client_initialized:
                last_err = None
                for p in os.environ.get("PATH", "").split(os.pathsep):
                    p = p.strip()
                    candidate = os.path.join(p, "oci.dll")
                    if p and os.path.isfile(candidate):
                        try:
                            oracledb.init_oracle_client(lib_dir=p)
                            _oracle_client_initialized = True
                            break
                        except Exception as e:
                            last_err = e
                if not _oracle_client_initialized:
                    try:
                        oracledb.init_oracle_client()
                        _oracle_client_initialized = True
                    except Exception as e:
                        last_err = e
                if not _oracle_client_initialized:
                    raise RuntimeError(
                        "Could not initialize Oracle thick client (needed for TNS alias / no host).\n"
                        "Please install Oracle Instant Client, or enter a Host in the connection form.\n"
                        f"Detail: {last_err}"
                    )
            dsn = self.service
        else:
            dsn = f"{self.host}:{self.port}/{self.service}"

        return oracledb.connect(user=self.user, password=self.password, dsn=dsn)

    def test_connection(self) -> Tuple[bool, str]:
        try:
            conn = self._connect()
            conn.close()
            return True, "Connection successful"
        except Exception as e:
            return False, str(e)

    def _table(self, sap_table: str) -> str:
        return build_table_name(self.schema, sap_table, self.sap_machine)

    def _fetch(self, conn, sql: str) -> pd.DataFrame:
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            col_names = [d[0].upper() for d in cursor.description]
            rows = cursor.fetchall()
        finally:
            cursor.close()
        df = pd.DataFrame(rows, columns=col_names)
        return df.fillna("").astype(str)

    def load_table(self, sap_table: str, filters: Optional[Dict] = None) -> pd.DataFrame:
        f = filters or {}
        if "plko_keys" in f and not f["plko_keys"]:
            return pd.DataFrame()
        sql = self._build_query(sap_table, f)
        conn = self._connect()
        try:
            df = self._fetch(conn, sql)
            df.columns = [c.upper() for c in df.columns]
            return df.drop(columns=["RN"], errors="ignore")
        finally:
            conn.close()

    def _build_query(self, sap_table: str, filters: Dict) -> str:
        dispatch = {
            "plko": self._plko_query,
            "plpo": self._plpo_query,
            "plmk": self._plmk_query,
            "mapl": self._mapl_query,
        }
        if sap_table in dispatch:
            return dispatch[sap_table](filters)
        return f"SELECT * FROM {self._table(sap_table)}"

    # ------------------------------------------------------------------ #
    # PLKO — deduplicated by ZAEHL, scoped via MAPL subquery              #
    # ------------------------------------------------------------------ #

    def _plko_query(self, filters: Dict) -> str:
        table = self._table("plko")
        mapl_table = self._table("mapl")

        material_clause = ""
        if filters.get("scope_materials") and filters.get("scope_plants"):
            mat_in = _in_clause("MATNR", filters["scope_materials"])
            plant_in = _in_clause("WERKS", filters["scope_plants"])
            material_clause = (
                f"AND PLNNR IN ("
                f"  SELECT PLNNR FROM {mapl_table} "
                f"  WHERE {mat_in} AND {plant_in}"
                f"  AND (LOEKZ IS NULL OR LOEKZ <> 'X'))"
            )

        return (
            f"SELECT * FROM ("
            f"  SELECT t.*, ROW_NUMBER() OVER ("
            f"      PARTITION BY PLNNR, PLNKN, WERKS ORDER BY ZAEHL DESC"
            f"  ) AS RN"
            f"  FROM {table} t"
            f"  WHERE VERWE = '5'"
            f"    AND STATU <> '7'"
            f"    AND (LOEKZ IS NULL OR LOEKZ <> 'X')"
            f"    {material_clause}"
            f") WHERE RN = 1"
        )

    # ------------------------------------------------------------------ #
    # PLAS CTE helper — shared by PLPO and PLMK queries                   #
    # ------------------------------------------------------------------ #

    def _plas_cte(self, filters: Dict) -> str:
        plas_table = self._table("plas")
        plko_clause = ""
        if filters.get("plko_keys"):
            plko_clause = f"AND {_in_clause('PLNNR', filters['plko_keys'])}"
        return (
            f"plas_dedup AS ("
            f"  SELECT * FROM ("
            f"    SELECT t.*, ROW_NUMBER() OVER ("
            f"        PARTITION BY PLNNR, PLNKN, PLNFL ORDER BY ZAEHL DESC"
            f"    ) AS RN"
            f"    FROM {plas_table} t"
            f"    WHERE (LOEKZ IS NULL OR LOEKZ <> 'X') {plko_clause}"
            f"  ) WHERE RN = 1"
            f")"
        )

    # ------------------------------------------------------------------ #
    # PLPO — joined to deduplicated PLAS                                   #
    # ------------------------------------------------------------------ #

    def _plpo_query(self, filters: Dict) -> str:
        table = self._table("plpo")
        plas_cte = self._plas_cte(filters)

        plko_clause = ""
        if filters.get("plko_keys"):
            plko_clause = f"AND {_in_clause('p.PLNNR', filters['plko_keys'])}"

        return (
            f"WITH {plas_cte} "
            f"SELECT p.* "
            f"FROM {table} p "
            f"INNER JOIN plas_dedup s "
            f"  ON  s.PLNNR = p.PLNNR AND s.PLNKN = p.PLNKN "
            f"  AND s.PLNFL = p.PLNFL AND s.VORNR = p.VORNR "
            f"WHERE (p.LOEKZ IS NULL OR p.LOEKZ <> 'X') {plko_clause}"
        )

    # ------------------------------------------------------------------ #
    # PLMK — joined to PLAS, deduplicated by ZAEHL                        #
    # (post-filtered by PLPO keys in orchestrator)                         #
    # ------------------------------------------------------------------ #

    def _plmk_query(self, filters: Dict) -> str:
        table = self._table("plmk")
        plas_cte = self._plas_cte(filters)

        plko_clause = ""
        if filters.get("plko_keys"):
            plko_clause = f"AND {_in_clause('plmk.PLNNR', filters['plko_keys'])}"

        return (
            f"WITH {plas_cte} "
            f"SELECT * FROM ("
            f"  SELECT plmk.*, ROW_NUMBER() OVER ("
            f"      PARTITION BY plmk.PLNNR, plmk.PLNKN, plmk.VORNR, plmk.MERKNR"
            f"      ORDER BY plmk.ZAEHL DESC"
            f"  ) AS RN"
            f"  FROM {table} plmk"
            f"  INNER JOIN plas_dedup s"
            f"    ON  s.PLNNR = plmk.PLNNR AND s.PLNKN = plmk.PLNKN"
            f"    AND s.PLNFL = plmk.PLNFL"
            f"  WHERE (plmk.LOEKZ IS NULL OR plmk.LOEKZ <> 'X') {plko_clause}"
            f") WHERE RN = 1"
        )

    # ------------------------------------------------------------------ #
    # MAPL — two variants depending on whether vendor scope is provided    #
    # ------------------------------------------------------------------ #

    def _mapl_query(self, filters: Dict) -> str:
        table = self._table("mapl")

        conditions = ["(LOEKZ IS NULL OR LOEKZ <> 'X')"]
        if filters.get("scope_materials"):
            conditions.append(_in_clause("MATNR", filters["scope_materials"]))
        if filters.get("scope_plants"):
            conditions.append(_in_clause("WERKS", filters["scope_plants"]))
        if filters.get("plko_keys"):
            conditions.append(_in_clause("PLNNR", filters["plko_keys"]))

        base_where = " AND ".join(conditions)
        scope_vendors = [v for v in filters.get("scope_vendors", []) if v]

        if not scope_vendors:
            return f"SELECT * FROM {table} WHERE {base_where}"

        ven_in = _in_clause("LIFNR", scope_vendors)
        return (
            f"WITH candidates AS ("
            f"  SELECT * FROM {table} WHERE {base_where}"
            f"), "
            f"vendor_in_scope AS ("
            f"  SELECT * FROM candidates WHERE {ven_in}"
            f"), "
            f"blank_vendor AS ("
            f"  SELECT c.* FROM candidates c"
            f"  WHERE (c.LIFNR IS NULL OR c.LIFNR = '')"
            f"    AND c.PLNKN = ("
            f"      SELECT MIN(c2.PLNKN) FROM candidates c2"
            f"      WHERE c2.MATNR = c.MATNR AND c2.WERKS = c.WERKS"
            f"        AND (c2.LIFNR IS NULL OR c2.LIFNR = '')"
            f"    )"
            f") "
            f"SELECT * FROM vendor_in_scope "
            f"UNION ALL "
            f"SELECT b.* FROM blank_vendor b "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM vendor_in_scope v WHERE v.MATNR = b.MATNR AND v.WERKS = b.WERKS"
            f")"
        )

    # ------------------------------------------------------------------ #
    # Scope helper (used by orchestrator for vendor lists)                 #
    # ------------------------------------------------------------------ #

    def load_scope(self, source: str, column: str, sheet: str = "Sheet1") -> List:
        if source.endswith((".xlsx", ".xls")):
            df = pd.read_excel(source, sheet_name=sheet, dtype=str)
        else:
            df = pd.read_csv(source, dtype=str)
        df.columns = [c.strip().upper() for c in df.columns]
        col = column.strip().upper()
        if col not in df.columns:
            return []
        return df[col].dropna().str.strip().unique().tolist()

    def load_key_mapping(self, km_cfg: dict) -> pd.DataFrame:
        source = km_cfg.get("source", "")
        if not source:
            return pd.DataFrame()
        sheet = km_cfg.get("sheet", "Sheet1")
        if source.endswith((".xlsx", ".xls")):
            df = pd.read_excel(source, sheet_name=sheet, dtype=str)
        else:
            df = pd.read_csv(source, dtype=str)
        df.columns = [c.strip().upper() for c in df.columns]
        return df.fillna("")
