import os
import tempfile
import shutil
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from src.loaders.file_loader import make_loader, FILE_TABLES
from src.loaders.oracle_loader import SERVICE_OPTIONS
from src.orchestrator import Orchestrator, load_settings, load_scope_cfg, summarise
from src.reporters.excel_reporter import generate_excel
from src.reporters.html_reporter import generate_html

st.set_page_config(page_title="SAP QM Comparator", layout="wide")

LAYERS = ["PLKO", "PLPO", "PLMK", "MAPL"]


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #
def _save_upload(uploaded) -> str:
    ext = ".xlsx" if uploaded.name.endswith(".xlsx") else ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    shutil.copyfileobj(uploaded, tmp)
    tmp.flush()
    return tmp.name


def _init_state():
    defaults = {
        "results": None,
        "settings": load_settings() if os.path.exists("config/settings.yaml") else {},
        "scope_cfg": load_scope_cfg() if os.path.exists("config/scope.yaml") else {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

page = st.sidebar.radio(
    "Navigation",
    ["① Data Source Config", "② Run Comparison", "③ Results & Download"],
)

# ================================================================== #
# PAGE 1 — Data Source Configuration                                   #
# ================================================================== #
if page == "① Data Source Config":
    st.title("Data Source Configuration")

    # ── Datasource forms ─────────────────────────────────────────── #
    def source_form(side: str, cfg: dict) -> dict:
        st.subheader(f"{side} System")
        src_type = st.selectbox(
            "Source Type", ["oracle", "excel", "csv"],
            index=["oracle", "excel", "csv"].index(cfg.get("type", "oracle")),
            key=f"{side}_type",
        )
        out: dict = {"type": src_type}

        if src_type == "oracle":
            current_svc = cfg.get("service", SERVICE_OPTIONS[0])
            svc_idx = SERVICE_OPTIONS.index(current_svc) if current_svc in SERVICE_OPTIONS else 0
            out["service"]     = st.selectbox("Oracle Service Name", SERVICE_OPTIONS, index=svc_idx, key=f"{side}_svc")
            out["user"]        = st.text_input("Username", cfg.get("user", ""), key=f"{side}_usr")
            out["password"]    = st.text_input(
                "Password",
                cfg.get("password", "") or os.getenv(f"{side.upper()}_DB_PASSWORD", ""),
                type="password", key=f"{side}_pwd",
            )
            out["schema"]      = st.text_input("Oracle Schema", cfg.get("schema", "mard_qmap_vert_sys"), key=f"{side}_schema")
            out["sap_machine"] = st.text_input("SAP Machine (e.g. poe, s4p)", cfg.get("sap_machine", ""), key=f"{side}_machine")
        else:
            label  = "Excel (.xlsx)" if src_type == "excel" else "CSV (.csv)"
            accept = ["xlsx"] if src_type == "excel" else ["csv"]
            st.caption(f"Upload one {label} file per table.")
            existing = cfg.get("file_mapping", {})
            file_mapping: dict = {}
            for tbl in FILE_TABLES:
                up = st.file_uploader(f"{tbl.upper()} file", type=accept, key=f"{side}_{tbl}_upload")
                file_mapping[tbl] = _save_upload(up) if up else existing.get(tbl, "")
            out["file_mapping"] = file_mapping

        return out

    col1, col2 = st.columns(2)
    settings = st.session_state["settings"]
    ds = settings.get("datasources", {})

    with col1:
        r3_cfg = source_form("R3", ds.get("r3", {}))
        if st.button("Test R/3 Connection"):
            ok, msg = make_loader(r3_cfg).test_connection()
            (st.success if ok else st.error)(msg)

    with col2:
        s4_cfg = source_form("S4", ds.get("s4", {}))
        if st.button("Test S/4 Connection"):
            ok, msg = make_loader(s4_cfg).test_connection()
            (st.success if ok else st.error)(msg)

    # ── Oracle Extraction Scope ──────────────────────────────────── #
    any_oracle_live = (
        r3_cfg.get("type", "oracle") == "oracle" or
        s4_cfg.get("type", "oracle") == "oracle"
    )
    scope_cfg = st.session_state["scope_cfg"]

    if any_oracle_live:
        st.divider()
        st.subheader("Oracle Extraction Scope")
        st.caption("Applies to Oracle data sources only.")

        st.markdown("**Material + Plant Scope**")
        st.caption(
            "Upload one file with MATNR and WERKS columns. "
            "Plant filter is optional — leave blank to use all plants in the file."
        )
        mat_file = st.file_uploader("Material+Plant Scope file (CSV or Excel)", type=["xlsx", "csv"], key="mat_scope")
        mc1, mc2, mc3 = st.columns(3)
        matnr_col = mc1.text_input("MATNR column", scope_cfg.get("scope_materials", {}).get("matnr_column", "MATNR"), key="mat_matnr")
        werks_col  = mc2.text_input("WERKS column",  scope_cfg.get("scope_materials", {}).get("werks_column", "WERKS"), key="mat_werks")
        plant      = mc3.text_input("Plant filter (optional)", scope_cfg.get("plant", ""), key="mat_plant")

        st.markdown("**Vendor Scope (optional)**")
        st.caption(
            "Upload one file with R/3 and S/4 vendor numbers. "
            "If not uploaded, all MAPL records within the material+plant scope are included."
        )
        ven_file = st.file_uploader("Vendor Scope file (CSV or Excel)", type=["xlsx", "csv"], key="ven_scope")
        vc1, vc2 = st.columns(2)
        ven_r3_col = vc1.text_input("R/3 vendor column", scope_cfg.get("scope_vendors", {}).get("r3_column", "R3_LIFNR"), key="ven_r3")
        ven_s4_col = vc2.text_input("S/4 vendor column", scope_cfg.get("scope_vendors", {}).get("s4_column", "S4_LIFNR"), key="ven_s4")
    else:
        mat_file = ven_file = None
        matnr_col = werks_col = plant = ven_r3_col = ven_s4_col = ""

    # ── Save ────────────────────────────────────────────────────── #
    if st.button("Save Configuration", type="primary"):
        mat_path = _save_upload(mat_file) if mat_file else scope_cfg.get("scope_materials", {}).get("source", "")
        ven_path = _save_upload(ven_file) if ven_file else scope_cfg.get("scope_vendors", {}).get("source", "")
        st.session_state["settings"] = {**settings, "datasources": {"r3": r3_cfg, "s4": s4_cfg}}
        st.session_state["scope_cfg"] = {
            "plant": plant,
            "scope_materials": {
                "source":       mat_path,
                "sheet":        "Sheet1",
                "matnr_column": matnr_col or "MATNR",
                "werks_column": werks_col or "WERKS",
            },
            "scope_vendors": {
                "source":    ven_path,
                "sheet":     "Sheet1",
                "r3_column": ven_r3_col or "R3_LIFNR",
                "s4_column": ven_s4_col or "S4_LIFNR",
            },
        }
        st.success("Configuration saved for this session.")

# ================================================================== #
# PAGE 2 — Run Comparison                                              #
# ================================================================== #
elif page == "② Run Comparison":
    st.title("Run Comparison")

    settings  = st.session_state["settings"]
    scope_cfg = st.session_state["scope_cfg"]

    # ── Mapping Files ──────────────────────────────────────────── #
    st.subheader("Mapping Files")
    st.caption(
        "Upload mapping files for key translation and field value comparison. "
        "All mappings are applied simultaneously before comparison runs."
    )

    km_cfg = settings.get("key_mapping", {})
    with st.expander("PLNNR / PLNKN Key Mapping"):
        st.caption("Preload or postload file linking R/3 plan numbers to S/4 plan numbers.")
        km_file  = st.file_uploader("File (CSV or Excel)", type=["xlsx", "csv"], key="km_file")
        km_sheet = st.text_input("Sheet name (Excel only)", km_cfg.get("sheet", "Sheet1"), key="km_sheet")
        c1, c2, c3, c4 = st.columns(4)
        col_r3nr = c1.text_input("R/3 PLNNR col", km_cfg.get("r3_plnnr_col", "R3_PLNNR"), key="km_r3nr")
        col_r3kn = c2.text_input("R/3 PLNKN col", km_cfg.get("r3_plnkn_col", "R3_PLNKN"), key="km_r3kn")
        col_s4nr = c3.text_input("S/4 PLNNR col", km_cfg.get("s4_plnnr_col", "S4_PLNNR"), key="km_s4nr")
        col_s4kn = c4.text_input("S/4 PLNKN col", km_cfg.get("s4_plnkn_col", "S4_PLNKN"), key="km_s4kn")
    km_path = _save_upload(km_file) if km_file else km_cfg.get("source", "")

    mf_cfg = settings.get("mapping_files", {})

    def mapping_form(key: str, label: str, default_r3: str, default_s4: str) -> dict:
        cfg = mf_cfg.get(key, {})
        with st.expander(label):
            up     = st.file_uploader("File (CSV or Excel)", type=["xlsx", "csv"], key=f"mf_{key}")
            sheet  = st.text_input("Sheet name (Excel only)", cfg.get("sheet", "Sheet1"), key=f"mf_{key}_sheet")
            c1, c2 = st.columns(2)
            r3_col = c1.text_input("R/3 value column", cfg.get("r3_key", default_r3), key=f"mf_{key}_r3")
            s4_col = c2.text_input("S/4 value column", cfg.get("s4_key", default_s4), key=f"mf_{key}_s4")
        return {
            "source": _save_upload(up) if up else cfg.get("source", ""),
            "sheet": sheet,
            "r3_key": r3_col,
            "s4_key": s4_col,
        }

    mf_vendor  = mapping_form("vendor",             "Vendor Mapping (LIFNR)",             "R3_LIFNR", "S4_LIFNR")
    mf_dmr     = mapping_form("dmr",                "DMR Mapping",                        "R3_DMR",   "S4_DMR")
    mf_samp    = mapping_form("sampling_procedure",  "Sampling Procedure Mapping (STELA)", "R3_PROC",  "S4_PROC")

    st.divider()
    st.subheader("Layers to compare")
    layer_cols = st.columns(len(LAYERS))
    layers = []
    for i, lyr in enumerate(LAYERS):
        if layer_cols[i].checkbox(lyr, value=True, key=f"lyr_{lyr}"):
            layers.append(lyr)

    if st.button("▶ Start Comparison", type="primary"):
        run_settings = {
            **settings,
            "key_mapping": {
                "source": km_path, "sheet": km_sheet,
                "r3_plnnr_col": col_r3nr, "r3_plnkn_col": col_r3kn,
                "s4_plnnr_col": col_s4nr, "s4_plnkn_col": col_s4kn,
            },
            "mapping_files": {
                "vendor":             mf_vendor,
                "dmr":                mf_dmr,
                "sampling_procedure": mf_samp,
            },
        }
        st.session_state["settings"] = run_settings

        progress_bar = st.progress(0)
        status_text  = st.empty()

        def progress_cb(layer: str, done: int, total: int):
            progress_bar.progress(done / total if total else 1)
            status_text.text(f"Processing {layer}…")

        try:
            orch = Orchestrator(run_settings, scope_cfg)
            results = orch.run(layers=layers, progress_cb=progress_cb)
            st.session_state["results"] = results
            progress_bar.progress(1.0)
            status_text.text("Done!")
            st.success("Comparison complete — go to Results & Download.")
        except Exception as e:
            st.error(f"Error: {e}")

# ================================================================== #
# PAGE 3 — Results & Download                                          #
# ================================================================== #
elif page == "③ Results & Download":
    st.title("Results & Download")

    results = st.session_state.get("results")
    if not results:
        st.info("No results yet — run a comparison first.")
        st.stop()

    settings  = st.session_state["settings"]
    inc_match = settings.get("report", {}).get("include_matches", False)

    summary_df = summarise(results)
    st.subheader("Summary")

    stat_cols = st.columns(len(summary_df) + 1)
    total_records = int(summary_df["Total"].sum())
    total_match   = int(summary_df["MATCH"].sum())
    overall_rate  = round(total_match / total_records * 100, 1) if total_records else 0

    stat_cols[0].metric("Overall Match Rate", f"{overall_rate}%")
    for i, row in summary_df.iterrows():
        stat_cols[i + 1].metric(
            row["Table"], f"{row['Match Rate %']}%",
            delta=f"{row['MISMATCH']} issues" if row["MISMATCH"] else "clean",
        )

    st.dataframe(summary_df, use_container_width=True)

    st.subheader("Diff Details")
    status_filter = st.selectbox(
        "Filter by status",
        ["All", "MISMATCH", "MISSING_IN_S4", "NEW_IN_S4", "UNMAPPED_KEY", "MATCH"],
    )
    table_filter = st.selectbox("Filter by table", ["All"] + list(results.keys()))

    from src.reporters.excel_reporter import _results_to_df

    for table, diffs in results.items():
        if table_filter not in ("All", table):
            continue
        df = _results_to_df(diffs, include_matches=True)
        if status_filter != "All":
            df = df[df["STATUS"] == status_filter]
        if df.empty:
            continue
        with st.expander(f"{table} — {len(df)} rows shown"):
            st.dataframe(df, use_container_width=True)

    st.divider()
    st.subheader("Download Reports")
    dl_col1, dl_col2 = st.columns(2)

    with dl_col1:
        excel_bytes = generate_excel(results, include_matches=inc_match)
        st.download_button(
            "⬇ Download Excel Report",
            data=excel_bytes,
            file_name="qm_comparison_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with dl_col2:
        html_str = generate_html(results, include_matches=inc_match)
        st.download_button(
            "⬇ Download HTML Report",
            data=html_str.encode(),
            file_name="qm_comparison_report.html",
            mime="text/html",
        )
