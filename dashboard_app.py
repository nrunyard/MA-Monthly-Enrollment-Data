"""
CMS Medicare Advantage Enrollment Dashboard
============================================
Reads combined_enrollment.csv.gz from the same directory.
Run: streamlit run dashboard_app.py
"""

import gzip
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Medicare Advantage Enrollment",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 1.5rem; }
  .block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ───────────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Loading enrollment data...")
def load_data() -> pd.DataFrame:
    here = Path(__file__).parent
    gz_path  = here / "combined_enrollment.csv.gz"
    csv_path = here / "combined_enrollment.csv"

    # Decompress if needed
    if gz_path.exists() and not csv_path.exists():
        with gzip.open(gz_path, "rb") as f_in, open(csv_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)

    if not csv_path.exists():
        st.error("combined_enrollment.csv not found. Please run the downloader script first.")
        st.stop()

    df = pd.read_csv(csv_path, dtype=str, encoding="latin-1")
    df.columns = [c.strip().strip('"') for c in df.columns]

    for col in ["State", "County", "Plan Type", "Contract ID",
                "Organization Name", "Organization Type"]:
        if col in df.columns:
            df[col] = df[col].fillna("Unknown").str.strip()

    df["report_period"] = df["report_period"].str.strip()
    df["Enrolled"] = pd.to_numeric(df["Enrolled"], errors="coerce").fillna(0)

    # Keep only rolling 24 months
    periods = sorted(df["report_period"].unique())
    if len(periods) > 24:
        periods = periods[-24:]
        df = df[df["report_period"].isin(periods)]

    return df


@st.cache_data(show_spinner=False)
def load_parent_org() -> dict:
    """Load Contract ID -> Parent Organization mapping from plan directory xlsx."""
    here = Path(__file__).parent
    candidates = list(here.rglob("MA_Contract_directory*.xlsx")) + \
                 list(here.rglob("MA_Plan_Directory*.xlsx"))
    if not candidates:
        return {}
    path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    try:
        df = pd.read_excel(path, dtype=str)
        df.columns = [c.replace("\n", " ").strip() if isinstance(c, str) else c
                      for c in df.columns]
        contract_col = next((c for c in df.columns
                             if "contract" in c.lower() and "number" in c.lower()), None)
        parent_col   = next((c for c in df.columns if "parent" in c.lower()), None)
        if contract_col and parent_col:
            return dict(zip(df[contract_col].str.strip(), df[parent_col].str.strip()))
    except Exception:
        pass
    return {}


df_full       = load_data()
parent_org_map = load_parent_org()
all_periods   = sorted(df_full["report_period"].unique())

if parent_org_map:
    df_full["Parent Organization"] = (
        df_full["Contract ID"].map(parent_org_map).fillna("Unknown / Other")
    )

# ── Sidebar filters ────────────────────────────────────────────────────────────

st.sidebar.title("🏥 MA Enrollment")
st.sidebar.markdown("---")
st.sidebar.subheader("Filters")

sel_state     = st.sidebar.multiselect("State",     sorted(df_full["State"].unique()))
sel_plan_type = st.sidebar.multiselect("Plan Type", sorted(df_full["Plan Type"].unique()))

if parent_org_map:
    sel_parent   = st.sidebar.multiselect("Parent Organization",
                                           sorted(df_full["Parent Organization"].unique()))
    sel_contract = []
else:
    sel_parent   = []
    sel_contract = st.sidebar.multiselect("Organization",
                                           sorted(df_full["Organization Name"].unique()))

county_options = sorted(
    df_full[df_full["State"].isin(sel_state)]["County"].unique()
    if sel_state else df_full["County"].unique()
)
sel_county = st.sidebar.multiselect("County", county_options)

st.sidebar.markdown("---")
if len(all_periods) > 1:
    period_range = st.sidebar.select_slider(
        "Period Range", options=all_periods,
        value=(all_periods[0], all_periods[-1])
    )
else:
    period_range = (all_periods[0], all_periods[0])
    st.sidebar.caption(f"Period: {all_periods[0]}")

# ── Apply filters ──────────────────────────────────────────────────────────────

@st.cache_data(show_spinner=False)
def apply_filters(state, plan_type, parent, contract, county, p_start, p_end):
    d = df_full.copy()
    d = d[(d["report_period"] >= p_start) & (d["report_period"] <= p_end)]
    if state:     d = d[d["State"].isin(state)]
    if plan_type: d = d[d["Plan Type"].isin(plan_type)]
    if parent:    d = d[d["Parent Organization"].isin(parent)]
    if contract:  d = d[d["Organization Name"].isin(contract)]
    if county:    d = d[d["County"].isin(county)]
    return d

df = apply_filters(
    tuple(sel_state), tuple(sel_plan_type), tuple(sel_parent),
    tuple(sel_contract), tuple(sel_county),
    period_range[0], period_range[1]
)

filtered_periods = sorted(df["report_period"].unique())
f_latest = filtered_periods[-1] if filtered_periods else None
f_prev   = filtered_periods[-2] if len(filtered_periods) > 1 else None
latest_df = df[df["report_period"] == f_latest] if f_latest else pd.DataFrame()

# ── MoM helper ─────────────────────────────────────────────────────────────────

def add_mom(base_df, prev_df, group_cols):
    if prev_df.empty:
        base_df["MoM Change"] = 0
        base_df["MoM %"]      = 0.0
        return base_df
    prev_agg = prev_df.groupby(group_cols)["Enrolled"].sum().reset_index()
    prev_agg.columns = group_cols + ["Prev"]
    merged = base_df.merge(prev_agg, on=group_cols, how="left")
    merged["Enrolled"] = pd.to_numeric(merged["Enrolled"], errors="coerce").fillna(0)
    merged["Prev"]     = pd.to_numeric(merged["Prev"],     errors="coerce").fillna(0)
    merged["MoM Change"] = (merged["Enrolled"] - merged["Prev"]).astype(int)
    merged["MoM %"] = (
        merged["MoM Change"].astype(float)
        .div(merged["Prev"].replace(0, float("nan")))
        .mul(100).round(2)
    )
    return merged

# ── KPIs ───────────────────────────────────────────────────────────────────────

st.title("Medicare Advantage Enrollment Dashboard")
st.caption(
    f"CMS MA/Part D Contract & Enrollment Data  ·  "
    f"{len(filtered_periods)} periods  ·  {period_range[0]} → {period_range[1]}"
)

latest_enrolled = float(df[df["report_period"] == f_latest]["Enrolled"].sum()) if f_latest else 0
prev_enrolled   = float(df[df["report_period"] == f_prev]["Enrolled"].sum())   if f_prev   else 0
mom_delta = latest_enrolled - prev_enrolled
mom_pct   = (mom_delta / prev_enrolled * 100) if prev_enrolled else 0

yoy_period   = filtered_periods[-13] if len(filtered_periods) >= 13 else None
yoy_enrolled = float(df[df["report_period"] == yoy_period]["Enrolled"].sum()) if yoy_period else None
yoy_delta    = (latest_enrolled - yoy_enrolled) if yoy_enrolled else None
yoy_pct      = (yoy_delta / yoy_enrolled * 100) if yoy_enrolled else None

k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total Enrolled",       f"{latest_enrolled:,.0f}", f"{mom_delta:+,.0f} MoM")
k2.metric("MoM Change",           f"{mom_delta:+,.0f}",      f"{mom_pct:+.2f}%")
k3.metric("YoY Change",
          f"{yoy_delta:+,.0f}"    if yoy_delta is not None else "—",
          f"{yoy_pct:+.2f}%"     if yoy_pct   is not None else "Need 13+ months")
k4.metric("Active Contracts",     f"{latest_df['Contract ID'].nunique():,}")
k5.metric("States / Territories", f"{latest_df['State'].nunique():,}")
k6.metric("Counties",             f"{latest_df['County'].nunique():,}")

st.markdown("---")
COLORS = px.colors.qualitative.Bold

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📈 Overview", "🗺 By State", "📍 By County", "🏢 By Contract", "📋 MoM Table"]
)

# ── Tab 1: Overview ────────────────────────────────────────────────────────────
with tab1:
    monthly = (
        df.groupby("report_period")["Enrolled"].sum()
        .reindex(filtered_periods).fillna(0).reset_index()
    )
    monthly.columns = ["Period", "Enrolled"]
    monthly["MoM Change"] = monthly["Enrolled"].diff().fillna(0)
    monthly["MoM %"]      = monthly["Enrolled"].pct_change().fillna(0) * 100

    c1, c2 = st.columns([3, 1])
    with c1:
        fig = px.area(monthly, x="Period", y="Enrolled",
                      title="Total MA Enrollment Over Time",
                      color_discrete_sequence=["#00d4ff"])
        fig.update_layout(hovermode="x unified", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        pt = latest_df.groupby("Plan Type")["Enrolled"].sum().reset_index()
        fig2 = px.pie(pt, names="Plan Type", values="Enrolled",
                      title="Plan Type Mix", color_discrete_sequence=COLORS, hole=0.4)
        fig2.update_traces(textinfo="percent+label")
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        fig3 = px.bar(monthly, x="Period", y="MoM Change",
                      title="Month-over-Month Change",
                      color="MoM Change",
                      color_continuous_scale=["#ef4444", "#1e2d45", "#10b981"],
                      color_continuous_midpoint=0)
        fig3.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)
    with c4:
        fig4 = px.line(monthly, x="Period", y="MoM %",
                       title="MoM % Change",
                       color_discrete_sequence=["#7c3aed"])
        fig4.add_hline(y=0, line_dash="dash", line_color="#64748b")
        st.plotly_chart(fig4, use_container_width=True)

# ── Tab 2: By State ────────────────────────────────────────────────────────────
with tab2:
    prev_df  = df[df["report_period"] == f_prev] if f_prev else pd.DataFrame()
    by_state = latest_df.groupby("State")["Enrolled"].sum().reset_index()
    by_state = add_mom(by_state, prev_df, ["State"])
    by_state = by_state.sort_values("Enrolled", ascending=False)

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(by_state.head(25), x="Enrolled", y="State", orientation="h",
                     title="Top 25 States", color="Enrolled",
                     color_continuous_scale="Blues")
        fig.update_layout(yaxis={"categoryorder": "total ascending"},
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        movers = by_state.reindex(
            by_state["MoM Change"].abs().sort_values(ascending=False).index
        ).head(20)
        fig2 = px.bar(movers, x="MoM Change", y="State", orientation="h",
                      title="Biggest MoM Movers",
                      color="MoM Change",
                      color_continuous_scale=["#ef4444", "#1e2d45", "#10b981"],
                      color_continuous_midpoint=0)
        fig2.update_layout(yaxis={"categoryorder": "total ascending"},
                           coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("State Detail")
    disp = by_state[["State", "Enrolled", "MoM Change", "MoM %"]].copy()
    disp["Enrolled"]   = disp["Enrolled"].apply(lambda x: f"{x:,.0f}")
    disp["MoM Change"] = disp["MoM Change"].apply(lambda x: f"{x:+,.0f}")
    disp["MoM %"]      = disp["MoM %"].apply(
        lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
    st.dataframe(disp, use_container_width=True, hide_index=True)

# ── Tab 3: By County ───────────────────────────────────────────────────────────
with tab3:
    prev_df   = df[df["report_period"] == f_prev] if f_prev else pd.DataFrame()
    by_county = latest_df.groupby(["State", "County"])["Enrolled"].sum().reset_index()
    by_county = add_mom(by_county, prev_df, ["State", "County"])
    by_county = by_county.sort_values("Enrolled", ascending=False)
    by_county["Label"] = by_county["County"] + ", " + by_county["State"]

    c1, c2 = st.columns([2, 1])
    with c1:
        fig = px.bar(by_county.head(30), x="Enrolled", y="Label", orientation="h",
                     title="Top 30 Counties", color="Enrolled",
                     color_continuous_scale="Purples")
        fig.update_layout(yaxis={"categoryorder": "total ascending"},
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        movers = by_county.reindex(
            by_county["MoM Change"].abs().sort_values(ascending=False).index
        ).head(15)
        fig2 = px.bar(movers, x="MoM Change", y="Label", orientation="h",
                      title="Biggest County Movers",
                      color="MoM Change",
                      color_continuous_scale=["#ef4444", "#1e2d45", "#10b981"],
                      color_continuous_midpoint=0)
        fig2.update_layout(yaxis={"categoryorder": "total ascending"},
                           coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.subheader("County Detail")
    disp = by_county[["State", "County", "Enrolled", "MoM Change", "MoM %"]].copy()
    disp["Enrolled"]   = disp["Enrolled"].apply(lambda x: f"{x:,.0f}")
    disp["MoM Change"] = disp["MoM Change"].apply(lambda x: f"{x:+,.0f}")
    disp["MoM %"]      = disp["MoM %"].apply(
        lambda x: f"{x:+.2f}%" if pd.notna(x) else "—")
    st.dataframe(disp, use_container_width=True, hide_index=True)

# ── Tab 4: By Contract ─────────────────────────────────────────────────────────
with tab4:
    group_col = "Parent Organization" if parent_org_map else "Organization Name"
    by_contract = (
        latest_df.groupby(["Contract ID", "Organization Name", "Plan Type"] +
                          ([group_col] if parent_org_map else []))["Enrolled"]
        .sum().reset_index().sort_values("Enrolled", ascending=False)
    )

    c1, c2 = st.columns(2)
    with c1:
        top20 = by_contract.head(20).copy()
        top20["Short"] = top20["Organization Name"].str[:35]
        fig = px.bar(top20, x="Enrolled", y="Short", orientation="h",
                     title="Top 20 Contracts", color="Enrolled",
                     color_continuous_scale="Teal")
        fig.update_layout(yaxis={"categoryorder": "total ascending"},
                          coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        pt = latest_df.groupby("Plan Type")["Enrolled"].sum().reset_index()
        fig2 = px.pie(pt, names="Plan Type", values="Enrolled",
                      title="By Plan Type", color_discrete_sequence=COLORS, hole=0.4)
        fig2.update_traces(textinfo="percent+label")
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    if parent_org_map:
        by_parent = (
            latest_df.groupby("Parent Organization")["Enrolled"].sum()
            .reset_index().sort_values("Enrolled", ascending=False)
        )
        st.subheader("By Parent Organization")
        fig3 = px.bar(by_parent.head(20), x="Enrolled", y="Parent Organization",
                      orientation="h", title="Top 20 Parent Organizations",
                      color="Enrolled", color_continuous_scale="Oranges")
        fig3.update_layout(yaxis={"categoryorder": "total ascending"},
                           coloraxis_showscale=False)
        st.plotly_chart(fig3, use_container_width=True)

    st.subheader("Contract Detail")
    disp = by_contract.copy()
    disp["Enrolled"] = disp["Enrolled"].apply(lambda x: f"{x:,.0f}")
    st.dataframe(disp, use_container_width=True, hide_index=True)

# ── Tab 5: MoM Table ───────────────────────────────────────────────────────────
with tab5:
    monthly = (
        df.groupby("report_period")["Enrolled"].sum()
        .reindex(filtered_periods).fillna(0).reset_index()
    )
    monthly.columns = ["Period", "Enrolled"]
    monthly["MoM Change"] = monthly["Enrolled"].diff().fillna(0).astype(int)
    monthly["MoM %"]      = (monthly["Enrolled"].pct_change().fillna(0) * 100).round(2)
    monthly = monthly.sort_values("Period", ascending=False)

    disp = monthly.copy()
    disp["Enrolled"]   = disp["Enrolled"].apply(lambda x: f"{x:,.0f}")
    disp["MoM Change"] = disp["MoM Change"].apply(lambda x: f"{x:+,.0f}")
    disp["MoM %"]      = disp["MoM %"].apply(lambda x: f"{x:+.2f}%")
    st.dataframe(disp, use_container_width=True, hide_index=True)

    st.download_button(
        "⬇ Download as CSV",
        monthly.to_csv(index=False).encode(),
        "ma_enrollment_mom.csv", "text/csv"
    )
