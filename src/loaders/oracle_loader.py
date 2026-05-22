from __future__ import annotations
from typing import Dict, List, Optional, Tuple
import pandas as pd
import oracledb
from .base import AbstractLoader

SERVICE_OPTIONS = [
    "REDLake_ZeusP_Consumer_DALI.world",
    "REDLake_ZeusQ_Consumer_DALI.world",
]


def build_table_name(schema: str, sap_table: str, sap_machine: str) -> str:
    return f"{schema}.v_rep_qmap_vert_sys_{sap_table}_{sap_machine}".lower()


class OracleLoader(AbstractLoader):
    """Loads SAP QM data from Oracle via TNS service name (thin mode)."""

    SAP_TABLES = ["plko", "plpo", "plmk", "mapl", "plas"]

    def __init__(self, config: dict):
        self.service = config["service"]
        self.host = config.get("host", "")
        self.port = int(config.get("port", 1521))
        self.user = config["user"]
        self.password = config["password"]
        self.schema = config["schema"]
        self.sap_machine = config["sap_machine"]

    def _connect(self):
        if self.host:
            dsn = f"{self.host}:{self.port}/{self.service}"
        else:
            dsn = self.service
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

    def load_table(self, sap_table: str, filters: Optional[Dict] = None) -> pd.DataFrame:
        f = filters or {}
        if "plko_keys" in f and not f["plko_keys"]:
            return pd.DataFrame()
        sql, params = self._build_query(sap_table, f)
        conn = self._connect()
        try:
            df = pd.read_sql(sql, conn, params=params)
            df.columns = [c.upper() for c in df.columns]
            df = df.drop(columns=["RN"], errors="ignore")
            return df
        finally:
            conn.close()

    def _build_query(self, sap_table: str, filters: Dict) -> Tuple[str, Dict]:
        dispatch = {
            "plko": self._plko_query,
            "plpo": self._plpo_query,
            "plmk": self._plmk_query,
            "mapl": self._mapl_query,
        }
        if sap_table in dispatch:
            return dispatch[sap_table](filters)
        return f"SELECT * FROM {self._table(sap_table)}", {}

    # ------------------------------------------------------------------ #
    # PLKO — deduplicated by ZAEHL, scoped via MAPL subquery              #
    # ------------------------------------------------------------------ #

    def _plko_query(self, filters: Dict) -> Tuple[str, Dict]:
        table = self._table("plko")
        mapl_table = self._table("mapl")
        params: Dict = {}

        material_clause = ""
        if filters.get("scope_materials") and filters.get("scope_plants"):
            material_clause = (
                f"AND PLNNR IN ("
                f"  SELECT PLNNR FROM {mapl_table} "
                f"  WHERE MATNR IN :scope_materials "
                f"  AND WERKS IN :scope_plants "
                f"  AND (LOEKZ IS NULL OR LOEKZ <> 'X'))"
            )
            params["scope_materials"] = tuple(filters["scope_materials"])
            params["scope_plants"] = tuple(filters["scope_plants"])

        sql = (
            f"SELECT * FROM ("
            f"  SELECT *, ROW_NUMBER() OVER ("
            f"      PARTITION BY PLNNR, PLNKN, WERKS ORDER BY ZAEHL DESC"
            f"  ) AS rn"
            f"  FROM {table}"
            f"  WHERE VERWE = '5'"
            f"    AND STATU <> '7'"
            f"    AND (LOEKZ IS NULL OR LOEKZ <> 'X')"
            f"    {material_clause}"
            f") WHERE rn = 1"
        )
        return sql, params

    # ------------------------------------------------------------------ #
    # PLAS CTE helper — shared by PLPO and PLMK queries                   #
    # ------------------------------------------------------------------ #

    def _plas_cte(self, params: Dict, filters: Dict) -> str:
        plas_table = self._table("plas")
        plko_clause = ""
        if filters.get("plko_keys"):
            plko_clause = "AND PLNNR IN :plko_keys"
            params["plko_keys"] = tuple(filters["plko_keys"])
        return (
            f"plas_dedup AS ("
            f"  SELECT * FROM ("
            f"    SELECT *, ROW_NUMBER() OVER ("
            f"        PARTITION BY PLNNR, PLNKN, PLNFL ORDER BY ZAEHL DESC"
            f"    ) AS rn"
            f"    FROM {plas_table}"
            f"    WHERE (LOEKZ IS NULL OR LOEKZ <> 'X') {plko_clause}"
            f"  ) WHERE rn = 1"
            f")"
        )

    # ------------------------------------------------------------------ #
    # PLPO — joined to deduplicated PLAS                                   #
    # ------------------------------------------------------------------ #

    def _plpo_query(self, filters: Dict) -> Tuple[str, Dict]:
        table = self._table("plpo")
        params: Dict = {}
        plas_cte = self._plas_cte(params, filters)

        plko_clause = ""
        if filters.get("plko_keys"):
            plko_clause = "AND p.PLNNR IN :plko_keys"

        sql = (
            f"WITH {plas_cte} "
            f"SELECT p.* "
            f"FROM {table} p "
            f"INNER JOIN plas_dedup s "
            f"  ON  s.PLNNR = p.PLNNR AND s.PLNKN = p.PLNKN "
            f"  AND s.PLNFL = p.PLNFL AND s.VORNR = p.VORNR "
            f"WHERE (p.LOEKZ IS NULL OR p.LOEKZ <> 'X') {plko_clause}"
        )
        return sql, params

    # ------------------------------------------------------------------ #
    # PLMK — joined to PLAS, deduplicated by ZAEHL                        #
    # (post-filtered by PLPO keys in orchestrator)                         #
    # ------------------------------------------------------------------ #

    def _plmk_query(self, filters: Dict) -> Tuple[str, Dict]:
        table = self._table("plmk")
        params: Dict = {}
        plas_cte = self._plas_cte(params, filters)

        plko_clause = ""
        if filters.get("plko_keys"):
            plko_clause = "AND plmk.PLNNR IN :plko_keys"

        sql = (
            f"WITH {plas_cte} "
            f"SELECT * FROM ("
            f"  SELECT plmk.*, ROW_NUMBER() OVER ("
            f"      PARTITION BY plmk.PLNNR, plmk.PLNKN, plmk.VORNR, plmk.MERKNR"
            f"      ORDER BY plmk.ZAEHL DESC"
            f"  ) AS rn"
            f"  FROM {table} plmk"
            f"  INNER JOIN plas_dedup s"
            f"    ON  s.PLNNR = plmk.PLNNR AND s.PLNKN = plmk.PLNKN"
            f"    AND s.PLNFL = plmk.PLNFL"
            f"  WHERE (plmk.LOEKZ IS NULL OR plmk.LOEKZ <> 'X') {plko_clause}"
            f") WHERE rn = 1"
        )
        return sql, params

    # ------------------------------------------------------------------ #
    # MAPL — two variants depending on whether vendor scope is provided    #
    # ------------------------------------------------------------------ #

    def _mapl_query(self, filters: Dict) -> Tuple[str, Dict]:
        table = self._table("mapl")
        params: Dict = {}

        conditions = ["(LOEKZ IS NULL OR LOEKZ <> 'X')"]
        if filters.get("scope_materials"):
            conditions.append("MATNR IN :scope_materials")
            params["scope_materials"] = tuple(filters["scope_materials"])
        if filters.get("scope_plants"):
            conditions.append("WERKS IN :scope_plants")
            params["scope_plants"] = tuple(filters["scope_plants"])
        if filters.get("plko_keys"):
            conditions.append("PLNNR IN :plko_keys")
            params["plko_keys"] = tuple(filters["plko_keys"])

        base_where = " AND ".join(conditions)
        scope_vendors = [v for v in filters.get("scope_vendors", []) if v]

        if not scope_vendors:
            return f"SELECT * FROM {table} WHERE {base_where}", params

        # With vendor scope: in-scope vendors OR first blank-vendor per MATNR+WERKS
        params["scope_vendors"] = tuple(scope_vendors)
        sql = (
            f"WITH candidates AS ("
            f"  SELECT * FROM {table} WHERE {base_where}"
            f"), "
            f"vendor_in_scope AS ("
            f"  SELECT * FROM candidates WHERE LIFNR IN :scope_vendors"
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
        return sql, params
