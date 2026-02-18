"""
CMS MA Enrollment - Streamlit Dashboard
========================================
Run with:
  streamlit run dashboard_app.py

Install deps:
  pip3 install streamlit pandas plotly
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Medicare Advantage Enrollment",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 1.6rem; }
  [data-testid="stMetricDelta"] { font-size: 0.9rem; }
  .block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Load data (cached so it only reads once) ──────────────────────────────────
@st.cache_data(show_spinner="Loading enrollment data...")
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, encoding="latin-1")
    df.columns = [c.strip().strip('"') for c in df.columns]
    df["Enrolled"] = pd.to_numeric(df["Enrolled"], errors="coerce").fillna(0)
    df["report_period"] = df["report_period"].str.strip()
    for col in ["State", "County", "Plan Type", "Contract ID",
                "Organization Name", "Organization Type"]:
        if col in df.columns:
            df[col] = df[col].fillna("Unknown").str.strip()
    return df

# ── Locate CSV ────────────────────────────────────────────────────────────────
DEFAULT_CSV = Path(__file__).parent / "combined_enrollment.csv"
if not DEFAULT_CSV.exists():
    st.error("combined_enrollment.csv not found. Run combine_ma_data.py first.")
    st.stop()

df_full = load_data(str(DEFAULT_CSV))
all_periods = sorted(df_full["report_period"].unique())
latest      = all_periods[-1]
prev        = all_periods[-2] if len(all_periods) > 1 else None

# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.title("🏥 MA Enrollment")
st.sidebar.markdown("---")
st.sidebar.subheader("Filters")

states     = ["All"] + sorted(df_full["State"].unique())
plan_types = ["All"] + sorted(df_full["Plan Type"].unique())
contracts  = ["All"] + sorted(df_full["Organization Name"].unique())

sel_state     = st.sidebar.selectbox("State",        states)
sel_plan_type = st.sidebar.selectbox("Plan Type",    plan_types)
sel_contract  = st.sidebar.selectbox("Organization", contracts)

# County depends on state
if sel_state != "All":
    county_options = ["All"] + sorted(df_full[df_full["State"] == sel_state]["County"].unique())
else:
    county_options = ["All"] + sorted(df_full["County"].unique())
sel_county = st.sidebar.selectbox("County", county_options)

st.sidebar.markdown("---")
period_range = st.sidebar.select_slider(
    "Period Range",
    options=all_periods,
    value=(all_periods[0], all_periods[-1]),
)

# ── Apply filters ─────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def apply_filters(state, plan_type, contract, county, p_start, p_end):
    d = df_full.copy()
    d = d[(d["report_period"] >= p_start) & (d["report_period"] <= p_end)]
    if state    != "All": d = d[d["State"]             == state]
    if plan_type!= "All": d = d[d["Plan Type"]          == plan_type]
    if contract != "All": d = d[d["Organization Name"]  == contract]
    if county   != "All": d = d[d["County"]             == county]
    return d

df = apply_filters(
    sel_state, sel_plan_type, sel_contract, sel_county,
    period_range[0], period_range[1]
)

filtered_periods = sorted(df["report_period"].unique())
f_latest = filtered_periods[-1] if filtered_periods else latest
f_prev   = filtered_periods[-2] if len(filtered_periods) > 1 else None

# ── KPIs ──────────────────────────────────────────────────────────────────────
st.title("Medicare Advantage Enrollment Dashboard")
st.caption(f"Source: CMS MA/Part D Contract & Enrollment Data  ·  {len(filtered_periods)} periods  ·  {period_range[0]} → {period_range[1]}")

latest_enrolled = int(df[df["report_period"] == f_latest]["Enrolled"].sum()) if f_latest else 0
prev_enrolled   = int(df[df["report_period"] == f_prev]["Enrolled"].sum())   if f_prev   else 0
mom_delta       = latest_enrolled - prev_enrolled
mom_pct         = (mom_delta / prev_enrolled * 100) if prev_enrolled else 0

yoy_period = filtered_periods[-13] if len(filtered_periods) >= 13 else None
yoy_enrolled = int(df[df["report_period"] == yoy_period]["Enrolled"].sum()) if yoy_period else None
yoy_delta    = (latest_enrolled - yoy_enrolled) if yoy_enrolled else None
yoy_pct      = (yoy_delta / yoy_enrolled * 100) if yoy_enrolled else None

num_contracts = df[df["report_period"] == f_latest]["Contract ID"].nunique()
num_states    = df[df["report_period"] == f_latest]["State"].nunique()
num_counties  = df[df["report_period"] == f_latest]["County"].nunique()

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total Enrolled",      f"{latest_enrolled:,.0f}",
          f"{mom_delta:+,.0f} MoM ({mom_pct:+.1f}%)")
k2.metric("MoM Change",          f"{mom_delta:+,.0f}",
          f"{mom_pct:+.2f}%")
k3.metric("YoY Change",
          f"{yoy_delta:+,.0f}" if yoy_delta is not None else "—",
          f"{yoy_pct:+.2f}%" if yoy_pct is not None else "Need 13+ months")
k4.metric("Active Contracts",    f"{num_contracts:,}")
k5.metric("States / Territories",f"{num_states:,}")
k6.metric("Counties",            f"{num_counties:,}")

st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 Overview", "🗺 By State", "📍 By County", "🏢 By Contract", "📋 MoM Table"]
)

COLORS = px.colors.qualitative.Bold

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════════
with tab1:
    monthly = (
        df.groupby("report_period")["Enrolled"].sum()
        .reindex(filtered_periods).fillna(0).reset_index()
    )
    monthly.columns = ["Period", "Enrolled"]
    monthly["MoM Change"] = monthly["Enrolled"].diff().fillna(0)
    monthly["MoM %"]      = monthly["Enrolled"].pct_change().fillna(0) * 100

    col1, col2 = st.columns([3, 1])

    with col1:
        fig = px.area(monthly, x="Period", y="Enrolled",
                      title="Total MA Enrollment Over Time",
                      labels={"Enrolled": "Enrollees"},
                      color_discrete_sequence=["#00d4ff"])
        fig.update_layout(hovermode="x unified", showlegend=False)
        fig.update_traces(hovertemplate="%{y:,.0f}")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        pt = (
            df[df["report_period"] == f_latest]
            .groupby("Plan Type")["Enrolled"].sum()
            .reset_index().sort_values("Enrolled", ascending=False)
        )
        fig2 = px.pie(pt, names="Plan Type", values="Enrolled",
                      title="Plan Type Mix (Latest)",
                      color_discrete_sequence=COLORS, hole=0.4)
        fig2.update_traces(textinfo="percent+label")
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    col3, col4 = st.columns(2)
    with col3:
        fig3 = px.bar(monthly, x="Period", y="MoM Change",
                      title="Month-over-Month Change",
                      color="MoM Change",
                      color_continuous_scale=["#ef4444", "#1e2d45", "#10b981"],
                      color_continuous_midpoint=0)
        fig3.update_layout(coloraxis_showscale=False, showlegend=False)
        fig3.update_traces(hovertemplate="%{x}<br>%{y:+,.0f}")
        st.plotly_chart(fig3, use_container_width=True)

    with col4:
        fig4 = px.line(monthly, x="Period", y="MoM %",
                       title="MoM % Change",
                       color_discrete_sequence=["#7c3aed"])
        fig4.add_hline(y=0, line_dash="dash", line_color="#64748b")
        fig4.update_traces(hovertemplate="%{x}<br>%{y:+.2f}%")
        st.plotly_chart(fig4, use_container_width=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — BY STATE
# ════════════════════════════════════════════════════════════════════════════════
with tab2:
    latest_df = df[df["report_period"] == f_latest]
    prev_df   = df[df["report_period"] == f_prev] if f_prev else pd.DataFrame()

    by_state = latest_df.groupby("State")["Enrolled"].sum().reset_index()
    if not prev_df.empty:
        prev_state = prev_df.groupby("State")["Enrolled"].sum().reset_index()
        prev_state.columns = ["State", "Prev"]
        by_state = by_state.merge(prev_state, on="State", how="left").fillna(0)
        by_state["MoM Change"] = (by_state["Enrolled"] - by_state["Prev"]).astype(int)
        by_state["MoM %"]      = (by_state["MoM Change"] / by_state["Prev"].replace(0, pd.NA) * 100).round(2)
    else:
        by_state["MoM Change"] = 0
        by_state["MoM %"]      = 0.0

    by_state = by_state.sort_values("Enrolled", ascending=False)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(by_state.head(25), x="Enrolled", y="State",
                     orientation="h", title="Top 25 States by Enrollment",
                     color="Enrolled", color_continuous_scale="Blues")
        fig.update_layout(yaxis={"categoryorder":"total ascending"}, coloraxis_showscale=False)
        fig.update_traces(hovertemplate="%{y}: %{x:,.0f}")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        mom_sorted = by_state.reindex(by_state["MoM Change"].abs().sort_values(ascending=False).index).head(20)
        fig2 = px.bar(mom_sorted, x="MoM Change", y="State",
                      orientation="h", title="Biggest MoM Movers",
                      color="MoM Change",
                      color_continuous_scale=["#ef4444","#1e2d45","#10b981"],
                      color_continuous_midpoint=0)
        fig2.update_layout(yaxis={"categoryorder":"total ascending"}, coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("State Detail")
    display = by_state[["State","Enrolled","MoM Change","MoM %"]].copy()
    display["Enrolled"]   = display["Enrolled"].apply(lambda x: f"{x:,.0f}")
    display["MoM Change"] = display["MoM Change"].apply(lambda x: f"{x:+,.0f}")
    display["MoM %"]      = display["MoM %"].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
    st.dataframe(display, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — BY COUNTY
# ════════════════════════════════════════════════════════════════════════════════
with tab3:
    latest_df = df[df["report_period"] == f_latest]
    prev_df   = df[df["report_period"] == f_prev] if f_prev else pd.DataFrame()

    by_county = latest_df.groupby(["State","County"])["Enrolled"].sum().reset_index()
    if not prev_df.empty:
        prev_county = prev_df.groupby(["State","County"])["Enrolled"].sum().reset_index()
        prev_county.columns = ["State","County","Prev"]
        by_county = by_county.merge(prev_county, on=["State","County"], how="left").fillna(0)
        by_county["MoM Change"] = (by_county["Enrolled"] - by_county["Prev"]).astype(int)
        by_county["MoM %"]      = (by_county["MoM Change"] / by_county["Prev"].replace(0, pd.NA) * 100).round(2)
    else:
        by_county["MoM Change"] = 0
        by_county["MoM %"]      = 0.0

    by_county = by_county.sort_values("Enrolled", ascending=False)
    by_county["Label"] = by_county["County"] + ", " + by_county["State"]

    col1, col2 = st.columns([2, 1])
    with col1:
        fig = px.bar(by_county.head(30), x="Enrolled", y="Label",
                     orientation="h", title="Top 30 Counties by Enrollment",
                     color="Enrolled", color_continuous_scale="Purples")
        fig.update_layout(yaxis={"categoryorder":"total ascending"}, coloraxis_showscale=False)
        fig.update_traces(hovertemplate="%{y}: %{x:,.0f}")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        mom_c = by_county.reindex(by_county["MoM Change"].abs().sort_values(ascending=False).index).head(15)
        fig2 = px.bar(mom_c, x="MoM Change", y="Label",
                      orientation="h", title="Biggest County MoM Movers",
                      color="MoM Change",
                      color_continuous_scale=["#ef4444","#1e2d45","#10b981"],
                      color_continuous_midpoint=0)
        fig2.update_layout(yaxis={"categoryorder":"total ascending"}, coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("County Detail")
    display = by_county[["State","County","Enrolled","MoM Change","MoM %"]].copy()
    display["Enrolled"]   = display["Enrolled"].apply(lambda x: f"{x:,.0f}")
    display["MoM Change"] = display["MoM Change"].apply(lambda x: f"{x:+,.0f}")
    display["MoM %"]      = display["MoM %"].apply(lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
    st.dataframe(display, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — BY CONTRACT
# ════════════════════════════════════════════════════════════════════════════════
with tab4:
    latest_df = df[df["report_period"] == f_latest]

    by_contract = (
        latest_df.groupby(["Contract ID","Organization Name","Plan Type"])["Enrolled"]
        .sum().reset_index().sort_values("Enrolled", ascending=False)
    )

    col1, col2 = st.columns(2)
    with col1:
        top20 = by_contract.head(20).copy()
        top20["Short"] = top20["Organization Name"].str[:35]
        fig = px.bar(top20, x="Enrolled", y="Short",
                     orientation="h", title="Top 20 Contracts by Enrollment",
                     color="Enrolled", color_continuous_scale="Teal")
        fig.update_layout(yaxis={"categoryorder":"total ascending"}, coloraxis_showscale=False)
        fig.update_traces(hovertemplate="%{y}: %{x:,.0f}")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        pt = latest_df.groupby("Plan Type")["Enrolled"].sum().reset_index()
        fig2 = px.pie(pt, names="Plan Type", values="Enrolled",
                      title="Enrollment by Plan Type",
                      color_discrete_sequence=COLORS, hole=0.4)
        fig2.update_traces(textinfo="percent+label")
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("Contract Detail")
    display = by_contract.copy()
    display["Enrolled"] = display["Enrolled"].apply(lambda x: f"{x:,.0f}")
    st.dataframe(display, use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — MoM TABLE
# ════════════════════════════════════════════════════════════════════════════════
with tab5:
    monthly = (
        df.groupby("report_period")["Enrolled"].sum()
        .reindex(filtered_periods).fillna(0).reset_index()
    )
    monthly.columns = ["Period", "Enrolled"]
    monthly["MoM Change"] = monthly["Enrolled"].diff().fillna(0).astype(int)
    monthly["MoM %"]      = (monthly["Enrolled"].pct_change().fillna(0) * 100).round(2)
    monthly = monthly.sort_values("Period", ascending=False)

    monthly["Enrolled"]   = monthly["Enrolled"].apply(lambda x: f"{x:,.0f}")
    monthly["MoM Change"] = monthly["MoM Change"].apply(lambda x: f"{x:+,.0f}")
    monthly["MoM %"]      = monthly["MoM %"].apply(lambda x: f"{x:+.2f}%")
    st.dataframe(monthly, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇ Download MoM Table as CSV",
        monthly.to_csv(index=False).encode(),
        "ma_enrollment_mom.csv", "text/csv"
    )
