from __future__ import annotations
from typing import Dict, List
from jinja2 import Template
import pandas as pd
from ..comparators.base import DiffResult
from ..orchestrator import summarise
from .excel_reporter import _results_to_df

_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SAP QM Migration Comparison Report</title>
<style>
  body { font-family: Arial, sans-serif; margin: 24px; background: #f5f5f5; }
  h1 { color: #2c3e50; }
  .cards { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
  .card { background: white; border-radius: 8px; padding: 16px 24px; box-shadow: 0 2px 4px rgba(0,0,0,.1); min-width: 120px; text-align: center; }
  .card .val { font-size: 2em; font-weight: bold; }
  .card .lbl { color: #666; font-size: .85em; }
  .match { background: #C6EFCE; }
  .mismatch { background: #FFEB9C; }
  .missing { background: #FFC7CE; }
  .new { background: #BDD7EE; }
  .unmapped { background: #E2EFDA; }
  details { background: white; border-radius: 8px; margin-bottom: 16px;
            padding: 12px 16px; box-shadow: 0 2px 4px rgba(0,0,0,.1); }
  summary { cursor: pointer; font-weight: bold; font-size: 1.1em; }
  table { border-collapse: collapse; width: 100%; margin-top: 12px; font-size: .85em; }
  th { background: #4472C4; color: white; padding: 6px 10px; text-align: left; }
  td { padding: 5px 10px; border-bottom: 1px solid #eee; }
  .filter-row { margin: 8px 0; }
  select { padding: 4px 8px; border-radius: 4px; border: 1px solid #ccc; }
</style>
</head>
<body>
<h1>SAP QM Migration — Inspection Plan Comparison</h1>
<p>Generated: {{ generated_at }}</p>

<div class="cards">
  {% for row in summary %}
  <div class="card">
    <div class="val">{{ row['Match Rate %'] }}%</div>
    <div class="lbl">{{ row['Table'] }} match rate</div>
  </div>
  {% endfor %}
  <div class="card mismatch">
    <div class="val">{{ total_mismatch }}</div>
    <div class="lbl">Total MISMATCH</div>
  </div>
  <div class="card missing">
    <div class="val">{{ total_missing }}</div>
    <div class="lbl">Total MISSING_IN_S4</div>
  </div>
  <div class="card new">
    <div class="val">{{ total_new }}</div>
    <div class="lbl">Total NEW_IN_S4</div>
  </div>
  <div class="card unmapped">
    <div class="val">{{ total_unmapped }}</div>
    <div class="lbl">Total UNMAPPED_KEY</div>
  </div>
</div>

{% for table, rows in tables.items() %}
<details {% if loop.first %}open{% endif %}>
  <summary>{{ table }} — {{ rows|length }} records shown</summary>
  <div class="filter-row">
    Filter by status:
    <select onchange="filterTable('{{ table }}', this.value)">
      <option value="">All</option>
      <option>MISMATCH</option>
      <option>MISSING_IN_S4</option>
      <option>NEW_IN_S4</option>
      <option>UNMAPPED_KEY</option>
      <option>MATCH</option>
    </select>
  </div>
  <table id="tbl_{{ table }}">
    <thead><tr>{% for col in cols[table] %}<th>{{ col }}</th>{% endfor %}</tr></thead>
    <tbody>
    {% for row in rows %}
    <tr class="row-{{ row.STATUS | lower | replace('_','-') }}"
        data-status="{{ row.STATUS }}"
        style="background: {{ status_color(row.STATUS) }}">
      {% for col in cols[table] %}<td>{{ row[col] }}</td>{% endfor %}
    </tr>
    {% endfor %}
    </tbody>
  </table>
</details>
{% endfor %}

<script>
function filterTable(tableId, status) {
  const tbl = document.getElementById('tbl_' + tableId);
  const rows = tbl.querySelectorAll('tbody tr');
  rows.forEach(r => {
    r.style.display = (!status || r.dataset.status === status) ? '' : 'none';
  });
}
</script>
</body>
</html>
"""

STATUS_COLORS = {
    "MATCH": "#C6EFCE",
    "MISMATCH": "#FFEB9C",
    "MISSING_IN_S4": "#FFC7CE",
    "NEW_IN_S4": "#BDD7EE",
    "UNMAPPED_KEY": "#E2EFDA",
}


def generate_html(results: Dict[str, List[DiffResult]], include_matches: bool = False) -> str:
    from datetime import datetime

    summary = summarise(results).to_dict("records")

    tables: Dict[str, List[Dict]] = {}
    cols: Dict[str, List[str]] = {}
    for table, diffs in results.items():
        df = _results_to_df(diffs, include_matches)
        if not df.empty:
            tables[table] = df.to_dict("records")
            cols[table] = list(df.columns)

    total_mismatch = sum(d.status == "MISMATCH" for diffs in results.values() for d in diffs)
    total_missing = sum(d.status == "MISSING_IN_S4" for diffs in results.values() for d in diffs)
    total_new = sum(d.status == "NEW_IN_S4" for diffs in results.values() for d in diffs)
    total_unmapped = sum(d.status == "UNMAPPED_KEY" for diffs in results.values() for d in diffs)

    tpl = Template(_TEMPLATE)
    tpl.globals["status_color"] = lambda s: STATUS_COLORS.get(s, "#ffffff")

    return tpl.render(
        summary=summary,
        tables=tables,
        cols=cols,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total_mismatch=total_mismatch,
        total_missing=total_missing,
        total_new=total_new,
        total_unmapped=total_unmapped,
    )
