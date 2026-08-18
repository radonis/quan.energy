"""
page_stats.py -- Page visit statistics (Admin > Stats).

Reads app_data/page_views.csv (columns: timestamp, page, session_id)
and renders three charts:
  1. Bar chart   -- total visits per page (all time)
  2. Line chart  -- daily visits, optionally per page
  3. Heatmap     -- hour-of-day x page (when is each page used)
"""

import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, timedelta

from shared import APP_DIR, CHART_THEME

_PV_PATH = os.path.join(APP_DIR, "app_data", "page_views.csv")
_COLS    = ["timestamp", "page", "session_id"]


def _load() -> pd.DataFrame:
    if not os.path.exists(_PV_PATH):
        return pd.DataFrame(columns=_COLS)
    df = pd.read_csv(_PV_PATH, header=None, names=_COLS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["date"] = df["timestamp"].dt.date
    df["hour"] = df["timestamp"].dt.hour + 1
    return df


def render_stats():
    st.title("Page Visit Statistics")

    df = _load()
    if df.empty:
        st.info("No visit data yet -- navigate a few pages and come back.")
        return

    # ── Filters ──────────────────────────────────────────────────────────────
    c1, c2 = st.columns([1, 2])
    days_back = c1.selectbox("Period", [7, 14, 30, 90, 365, 0],
                             format_func=lambda x: "All time" if x == 0 else f"Last {x} days")
    if days_back:
        cutoff = date.today() - timedelta(days=days_back)
        df = df[df["date"] >= cutoff]

    all_pages  = sorted(df["page"].unique())
    sel_pages  = c2.multiselect("Filter pages", all_pages, default=[])
    if sel_pages:
        df = df[df["page"].isin(sel_pages)]

    if df.empty:
        st.info("No data for the selected filters.")
        return

    total_visits  = len(df)
    unique_sess   = df["session_id"].nunique()
    unique_pages  = df["page"].nunique()
    m1, m2, m3 = st.columns(3)
    m1.metric("Total page views", total_visits)
    m2.metric("Unique sessions", unique_sess)
    m3.metric("Pages visited", unique_pages)

    st.markdown("---")

    # ── 1. Bar chart: visits per page ────────────────────────────────────────
    st.subheader("Visits per page")
    by_page = (df.groupby("page").size()
                 .reset_index(name="visits")
                 .sort_values("visits", ascending=True))
    fig1 = go.Figure(go.Bar(
        x=by_page["visits"], y=by_page["page"],
        orientation="h",
        marker_color="#2979ff",
        text=by_page["visits"], textposition="outside",
    ))
    fig1.update_layout(
        **CHART_THEME,
        height=max(300, len(by_page) * 24 + 60),
        margin=dict(l=120, r=60, t=10, b=30),
        xaxis_title="Visits",
        yaxis_title="",
    )
    st.plotly_chart(fig1, use_container_width=True)

    # ── 2. Line chart: daily visits ──────────────────────────────────────────
    st.subheader("Daily visits")
    top5 = (df.groupby("page").size()
              .nlargest(5).index.tolist())
    show_breakdown = st.checkbox("Show top-5 pages", value=False)

    fig2 = go.Figure()
    if show_breakdown:
        for pg in top5:
            daily = (df[df["page"] == pg]
                       .groupby("date").size()
                       .reset_index(name="visits"))
            fig2.add_trace(go.Scatter(
                x=daily["date"].astype(str), y=daily["visits"],
                mode="lines+markers", name=pg,
            ))
    else:
        daily_all = df.groupby("date").size().reset_index(name="visits")
        fig2.add_trace(go.Scatter(
            x=daily_all["date"].astype(str), y=daily_all["visits"],
            mode="lines+markers", name="All pages",
            line=dict(color="#2979ff", width=2),
            fill="tozeroy", fillcolor="rgba(41,121,255,0.12)",
        ))
    fig2.update_layout(
        **CHART_THEME,
        height=320,
        xaxis=dict(title="Date", type="category"),
        yaxis_title="Visits",
        margin=dict(l=50, r=20, t=10, b=60),
        legend=dict(orientation="h", y=-0.25),
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ── 3. Heatmap: hour x page ──────────────────────────────────────────────
    st.subheader("Usage by hour of day")
    pivot = (df.groupby(["page", "hour"]).size()
               .unstack(fill_value=0))
    all_hours = list(range(1, 25))
    pivot = pivot.reindex(columns=all_hours, fill_value=0)

    fig3 = go.Figure(go.Heatmap(
        z=pivot.values,
        x=[str(h) for h in pivot.columns],
        y=pivot.index.tolist(),
        colorscale="Blues",
        hovertemplate="Page: %{y}<br>Hour: %{x}<br>Visits: %{z}<extra></extra>",
        xgap=1, ygap=1,
    ))
    fig3.update_layout(
        **CHART_THEME,
        height=max(280, len(pivot) * 22 + 80),
        xaxis=dict(title="Hour of day (1-24)", type="category"),
        yaxis_title="",
        margin=dict(l=140, r=20, t=10, b=50),
    )
    st.plotly_chart(fig3, use_container_width=True)

    with st.expander("Raw data"):
        st.dataframe(
            df[["timestamp", "page", "session_id"]]
              .sort_values("timestamp", ascending=False)
              .reset_index(drop=True),
            use_container_width=True,
        )
