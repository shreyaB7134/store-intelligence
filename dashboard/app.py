"""
Store Intelligence Platform - Live Dashboard
Auto-refreshes every 5 seconds.
"""
import time
import os
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv
import streamlit as st
import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Load environment variables from .env if present
load_dotenv()

# --- Config ---
API_BASE = os.getenv("API_BASE_URL", "http://api:8000")
STORE_ID = os.getenv("STORE_ID", "ST1008")
REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "5"))

st.set_page_config(
    page_title="Store Intelligence Platform",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom CSS for premium look
st.markdown("""
<style>
    .main { background-color: #0f1117; }
    .metric-card {
        background: linear-gradient(135deg, #1e2130, #2d3250);
        border-radius: 12px;
        padding: 20px;
        border: 1px solid #3d4675;
        text-align: center;
    }
    .anomaly-critical { border-left: 4px solid #ff4b4b; padding: 8px; margin: 4px 0; }
    .anomaly-warn { border-left: 4px solid #ffa500; padding: 8px; margin: 4px 0; }
    .anomaly-info { border-left: 4px solid #4287f5; padding: 8px; margin: 4px 0; }
    h1 { color: #7c83fd; }
</style>
""", unsafe_allow_html=True)


def fetch(endpoint: str) -> Optional[dict]:
    """Fetch JSON from the API, returning None on any error."""
    try:
        # millisecond timestamp to bust CDN/proxy caches
        params = {"_t": int(time.time() * 1000)}
        r = httpx.get(f"{API_BASE}{endpoint}", params=params, timeout=5.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def render_header():
    """Render the top header bar with title, API health, and feed status."""
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.title("🛒 Store Intelligence Platform")
        st.caption(f"Store: **{STORE_ID}** | Last updated: {datetime.now().strftime('%H:%M:%S')}")
    with col2:
        health = fetch("/health")
        if health:
            status = health.get("status", "unknown")
            color = "🟢" if status == "healthy" else "🔴"
            st.metric("API Status", f"{color} {status.title()}")
    with col3:
        if health:
            stale = health.get("stale_feed", False)
            st.metric("Feed", "⚠️ Stale" if stale else "✅ Live")


def render_kpi_row(metrics: Optional[dict]):
    """Render the five main KPI tiles across a single row."""
    st.subheader("📊 Key Performance Indicators")
    cols = st.columns(5)

    if not metrics:
        for col in cols:
            with col:
                st.metric("--", "N/A")
        return

    with cols[0]:
        st.metric("👤 Unique Visitors", metrics.get("unique_visitors", 0))
    with cols[1]:
        conv = metrics.get("conversion_rate", 0)
        st.metric("🛒 Conversion Rate", f"{conv:.1%}")
    with cols[2]:
        dwell = metrics.get("average_dwell_ms", 0)
        dwell_min = round(dwell / 60000, 1) if dwell else 0
        st.metric("⏱ Avg Dwell", f"{dwell_min} min")
    with cols[3]:
        st.metric("💳 Queue Depth", metrics.get("queue_depth", 0))
    with cols[4]:
        aband = metrics.get("abandonment_rate", 0)
        st.metric("🚫 Abandonment", f"{aband:.1%}")


def render_funnel(funnel: Optional[dict]):
    """Render the customer journey funnel as an interactive Plotly funnel chart."""
    if not funnel or not funnel.get("stages"):
        st.info("No funnel data available")
        return

    stages = funnel["stages"]
    df = pd.DataFrame(stages)

    fig = go.Figure(go.Funnel(
        y=df["stage"],
        x=df["count"],
        textinfo="value+percent initial",
        marker_color=["#7c83fd", "#56ccf2", "#f2994a", "#6fcf97"],
    ))
    fig.update_layout(
        title="Customer Journey Funnel",
        paper_bgcolor="#1e2130",
        plot_bgcolor="#1e2130",
        font_color="white",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_heatmap(heatmap: Optional[dict]):
    """Render a horizontal bar chart heatmap of zone popularity scores."""
    if not heatmap or not heatmap.get("zones"):
        st.info("No heatmap data available")
        return

    zones = heatmap["zones"]
    df = pd.DataFrame(zones).sort_values("score", ascending=True)

    fig = px.bar(
        df, x="score", y="zone_id", orientation="h",
        color="score",
        color_continuous_scale="Viridis",
        title="Zone Popularity Heatmap",
        labels={"score": "Normalized Score", "zone_id": "Zone"},
        text="visit_count",
    )
    fig.update_layout(
        paper_bgcolor="#1e2130",
        plot_bgcolor="#1e2130",
        font_color="white",
        height=max(300, len(zones) * 40),
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_anomalies(anomalies: Optional[dict]):
    """Render the live anomaly feed with colour-coded severity cards."""
    if not anomalies:
        st.info("No anomaly data")
        return

    items = anomalies.get("anomalies", [])
    if not items:
        st.success("✅ No anomalies detected")
        return

    for a in items:
        severity = a.get("severity", "INFO")
        css_class = {
            "CRITICAL": "anomaly-critical",
            "WARN": "anomaly-warn",
            "INFO": "anomaly-info",
        }.get(severity, "anomaly-info")

        icon = {"CRITICAL": "🔴", "WARN": "⚠️", "INFO": "ℹ️"}.get(severity, "ℹ️")

        st.markdown(
            f"""<div class="{css_class}">
            <strong>{icon} [{severity}] {a.get('anomaly_type', '')}</strong><br/>
            {a.get('message', '')}<br/>
            <em>💡 {a.get('suggested_action', '')}</em>
            </div>""",
            unsafe_allow_html=True,
        )


def main():
    render_header()
    st.divider()

    # Fetch all data in parallel-ish (sequential for simplicity; httpx is sync here)
    metrics = fetch(f"/stores/{STORE_ID}/metrics")
    funnel = fetch(f"/stores/{STORE_ID}/funnel")
    heatmap = fetch(f"/stores/{STORE_ID}/heatmap")
    anomalies = fetch(f"/stores/{STORE_ID}/anomalies")

    # KPI Row
    render_kpi_row(metrics)
    st.divider()

    # Main content grid
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("🎯 Customer Journey Funnel")
        render_funnel(funnel)

    with col2:
        st.subheader("🔥 Zone Heatmap")
        render_heatmap(heatmap)

    st.divider()
    st.subheader("🚨 Anomaly Feed")
    render_anomalies(anomalies)

    # Auto-refresh loop: sleep then force a full Streamlit rerun
    time.sleep(REFRESH_SECONDS)
    st.rerun()


if __name__ == "__main__":
    main()
