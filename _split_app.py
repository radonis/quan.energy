"""
_split_app.py — one-time script to split app.py into pages/*.py modules.
Run from the app directory: python _split_app.py
"""

import os, re, textwrap

APP   = "app.py"
PAGES = "pages"
os.makedirs(PAGES, exist_ok=True)

with open(APP, encoding="utf-8") as f:
    lines = f.readlines()

def extract(start, end):
    """Return lines[start-1 : end-1] as a single string (1-indexed, inclusive)."""
    return "".join(lines[start - 1 : end])

def indent_as_function(code, fn_name):
    """
    Wrap a page block (which starts with 'elif page == "X":' or 'if page == "X":')
    as 'def fn_name():' with body indented by 4 spaces.
    """
    # Remove the first line (elif/if page == ...)
    body_lines = code.split("\n", 1)[1] if "\n" in code else ""
    # Dedent to remove the 4-space indent from the elif block
    body = textwrap.dedent(body_lines)
    # Re-indent everything by 4 spaces
    indented = "\n".join("    " + l if l.strip() else l for l in body.split("\n"))
    return f"def {fn_name}():\n{indented}\n"

# ── Page ranges (start line, end line — 1-indexed, inclusive) ─────────────────
SECTIONS = {
    "spot": {
        "header": '''\
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, calendar, re as _re
from datetime import date, timedelta
from shared import (
    CHART_THEME, APP_DIR,
    load_prices, load_de_prices,
)
''',
        "pages": [
            ("render_prices",      398,  649),
            ("render_german_spot", 2768, 2950),
        ],
    },
    "trading": {
        "header": '''\
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, json
from datetime import date, timedelta
from shared import (
    CHART_THEME, APP_DIR,
    load_prices, load_trades, save_trades,
    load_tso_trades, save_tso_trades, calc_pnl,
    TRADES_PATH, TSO_TRADES_PATH,
)
''',
        "pages": [
            ("render_fixtrade",   653,  989),
            ("render_tsotrade",   993, 1522),
            ("render_pnl",       1526, 1809),
            ("render_fix_heatmap", 1813, 2110),
            ("render_tso_heatmap", 2114, 2411),
        ],
    },
    "tso": {
        "header": '''\
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, importlib.util
from datetime import date, timedelta
from shared import (
    CHART_THEME, APP_DIR,
    load_pse, load_pk5, load_pk5for, load_pse_demand,
    PK5FOR_PATH,
)
''',
        "pages": [
            ("render_pse",           2487, 2763),
            ("render_pk5",           2954, 3126),
            ("render_pk5_snapshots", 5083, 5264),
            ("render_power_demand",  5268, 5500),
            ("render_pse_viewer",    5647, 5847),
        ],
    },
    "forward": {
        "header": '''\
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os, importlib.util
from datetime import date, timedelta
import matplotlib
import matplotlib.pyplot as plt
from shared import (
    CHART_THEME, APP_DIR,
    load_otf_ee, load_otf_gas, load_ets, load_eurpln, load_pscmi,
    load_rb_h_cached, load_de_prices,
    OTF_EE_PATH, OTF_GAS_PATH, ETS_CO2_PATH,
    CDS_PARAMS_PATH, CCS_PARAMS_PATH,
    _otf_delivery_hours,
)
''',
        "pages": [
            ("render_ets",      3130, 3268),
            ("render_coal",     3272, 3384),
            ("render_otf_ee",   3388, 3606),
            ("render_cds",      3610, 3786),
            ("render_ccs",      3790, 3979),
            ("render_otf_gas",  3983, 4166),
            ("render_compare",  4170, 4458),
            ("render_liquidity",4462, 4651),
        ],
    },
    "forecast": {
        "header": '''\
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
from datetime import date, timedelta, datetime
from shared import (
    CHART_THEME, APP_DIR,
    FORECAST_DB_PATH, DE_FORE_PATH,
    load_prices, load_pk5,
)
''',
        "pages": [
            ("render_forecast",     5851, 5987),
            ("render_weekly",       5991, 6284),
            ("render_plotting",     6288, 6609),
            ("render_performance",  6613, len(lines)),
        ],
    },
    "admin": {
        "header": '''\
import streamlit as st
import pandas as pd
import os, importlib.util
from datetime import date
from shared import (
    APP_DIR,
    PARQUET_PATH, PSE_PRICES_PATH, PK5_PATH,
    DE_PRICES_PATH, OTF_EE_PATH, OTF_GAS_PATH,
    ETS_CO2_PATH, RB_H_PATH, PSE_DEMAND_PATH,
    load_pse,
    CDS_PARAMS_PATH, CCS_PARAMS_PATH,
)
''',
        "pages": [
            ("render_parquet", 2415, 2483),
            ("render_logs",    4655, 4708),
            ("render_cds_config", 4712, 4888),
            ("render_ccs_config", 4892, 5079),
            ("render_admin",   5504, 5643),
        ],
    },
}

for module_name, section in SECTIONS.items():
    out_path = os.path.join(PAGES, f"{module_name}.py")
    parts = [section["header"]]
    parts.append("\n")

    for fn_name, start, end in section["pages"]:
        raw = extract(start, end)
        wrapped = indent_as_function(raw, fn_name)
        # Fix os.path.dirname(__file__) → APP_DIR
        wrapped = wrapped.replace("os.path.dirname(__file__)", "APP_DIR")
        parts.append(wrapped)
        parts.append("\n\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))
    print(f"Written: {out_path}")

print("\nDone. Review each pages/*.py file for any remaining issues.")
