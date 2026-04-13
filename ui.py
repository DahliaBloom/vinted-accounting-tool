"""UI helpers, styling, formatters, and chart builders for the Vinted Tracker."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

ACCENT = "#637AB6"
TEAL   = "#14B8A6"
ORANGE = "#F97316"
GREEN  = "#22C55E"
RED    = "#EF4444"
PURPLE = "#A855F7"
AMBER  = "#F59E0B"
CHART_SEQ = [ACCENT, TEAL, ORANGE, GREEN, RED, PURPLE, AMBER]

STATUS_COLORS = {
    "In Shipping": "#3B82F6",
    "Pending":     "#F97316",
    "Listed":      "#637AB6",
    "Sold":        "#22C55E",
    "Cancelled":   "#6B7280",
}

# STATUS_BADGE lives here (not in utils) because the icon tokens are
# Streamlit-specific presentation strings, not domain data.
STATUS_BADGE = {
    "All Items":   ("blue",    ":material/inventory_2:"),
    "In Shipping": ("blue",    ":material/local_shipping:"),
    "Pending":     ("orange",  ":material/deployed_code_history:"),
    "Listed":      ("primary", ":material/sell:"),
    "Sold":        ("green",   ":material/check_circle:"),
    "Cancelled":   ("gray",    ":material/cancel:"),
}

# ---------------------------------------------------------------------------
# Chart / UI constants
# ---------------------------------------------------------------------------

# Earliest expected data date; used for the "All Time" period range.
EPOCH_START = date(2020, 1, 1)

# Rolling average window (days) used in time-series charts.
ROLLING_WINDOW_DAYS: int = 7

# Number of bins in ROI / time-to-sell histograms.
HISTOGRAM_BINS: int = 20

# Number of months shown in the monthly trend comparison chart.
MONTHLY_TREND_COUNT: int = 6

# Maximum categories shown in Finance breakdown bar charts.
TOP_N_BREAKDOWN: int = 12

# Maximum categories shown in Insights dimension bar charts.
TOP_N_DIMENSION: int = 10

# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def inject_custom_css() -> None:
    """Inject global custom CSS once per page load."""
    st.html("""<style>
/* Metric cards */
[data-testid="stMetric"] {
    background: rgba(32,42,68,0.55);
    border: 1px solid rgba(99,122,182,0.18);
    border-radius: 10px;
    padding: 10px 14px 6px 14px;
}
[data-testid="stMetricLabel"] { font-size: 0.74rem; opacity: 0.78; }
[data-testid="stMetricValue"] { font-size: 1.30rem; }

/* Tighter border-containers */
[data-testid="stVerticalBlockBorderWrapper"] > div { padding: 10px 14px !important; }

/* Subtle shadow on bordered containers for depth */
[data-testid="stVerticalBlockBorderWrapper"] {
    box-shadow: 0 2px 8px rgba(0,0,0,0.18);
}

/* Muted captions */
[data-testid="stCaptionContainer"] { opacity: 0.72; }

/* Metric delta colour fix — positive green, negative red */
[data-testid="stMetricDelta"] svg { display: none; }
[data-testid="stMetricDelta"] { font-size: 0.72rem; }

/* Tab hover */
button[data-baseweb="tab"] { transition: background 0.15s; }
button[data-baseweb="tab"]:hover { background: rgba(99,122,182,0.08) !important; }

/* Collapse the "Direction" radio label inside sort row */
.sort-radio [data-testid="stWidgetLabel"] { display: none; }

/* Hide streamlit footer */
footer { visibility: hidden; }
</style>""")


# ---------------------------------------------------------------------------
# Accent bar helper
# ---------------------------------------------------------------------------


def accent_bar(color: str) -> None:
    """Inject a 3 px coloured accent bar — call as first element inside a bordered container."""
    st.html(
        f'<div style="height:3px;background:linear-gradient(90deg,{color}cc,transparent);'
        f'border-radius:4px;margin-bottom:6px"></div>'
    )


# ---------------------------------------------------------------------------
# Chart styling
# ---------------------------------------------------------------------------


def style_fig(
    fig: go.Figure,
    height: int = 320,
    money_y: bool = False,
    pct_y: bool = False,
    date_x: bool = False,
    zero_line: bool = False,
    hovermode: str = "x unified",
) -> go.Figure:
    """Apply dark-theme chart styling with optional axis formatting.

    Pass hovermode="closest" for horizontal bar / scatter charts where
    "x unified" would group by the numeric value axis instead of category.
    """
    yaxis_kw: dict[str, Any] = dict(
        gridcolor="rgba(99,122,182,0.10)",
        zerolinecolor="rgba(99,122,182,0.15)",
    )
    if money_y:
        yaxis_kw["tickprefix"] = "€"
    if pct_y:
        yaxis_kw["ticksuffix"] = "%"

    xaxis_kw: dict[str, Any] = dict(
        gridcolor="rgba(99,122,182,0.10)",
        zerolinecolor="rgba(99,122,182,0.15)",
    )
    if date_x:
        xaxis_kw["tickformat"] = "%b %d"

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#C8CCD8", size=11, family="sans-serif"),
        xaxis=xaxis_kw,
        yaxis=yaxis_kw,
        margin=dict(l=0, r=4, t=36, b=0),
        height=height,
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02,
            xanchor="right", x=1, font=dict(size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        hovermode=hovermode,
        colorway=CHART_SEQ,
    )
    if zero_line:
        fig.add_hline(y=0, line_dash="dot",
                      line_color="rgba(255,255,255,0.20)", line_width=1)
    return fig


# ---------------------------------------------------------------------------
# Reusable chart builders
# ---------------------------------------------------------------------------


def revenue_profit_bar(
    grp: pd.DataFrame,
    title: str,
    height: int = 280,
    top_n: int = TOP_N_DIMENSION,
) -> go.Figure:
    """Build an overlaid horizontal Revenue + Profit bar chart.

    *grp* must have columns ``Revenue`` and ``Profit``.
    """
    grp = grp.sort_values("Revenue", ascending=True).tail(top_n)
    bar_colors = [GREEN if (pd.notna(p) and p >= 0) else RED for p in grp["Profit"]]
    fig = go.Figure()
    fig.add_bar(
        y=grp.index, x=grp["Revenue"], name="Revenue",
        orientation="h", marker_color=ACCENT,
        hovertemplate="%{y}: €%{x:,.2f}<extra>Revenue</extra>",
    )
    fig.add_bar(
        y=grp.index, x=grp["Profit"], name="Profit",
        orientation="h", marker_color=bar_colors, opacity=0.85,
        hovertemplate="%{y}: €%{x:,.2f}<extra>Profit</extra>",
    )
    fig.update_layout(title=title, barmode="overlay", yaxis_title="")
    return style_fig(fig, height=height, hovermode="closest")


# ---------------------------------------------------------------------------
# Column config factory
# ---------------------------------------------------------------------------


def money_column_config(**overrides: Any) -> dict[str, Any]:
    """Return the standard column_config dict for money/ROI columns.

    Constructed as a function (not a module-level dict) so that
    ``st.column_config`` objects are created at render time.
    Call with keyword overrides to extend or replace individual entries::

        money_column_config(sku=st.column_config.NumberColumn("SKU", step=1))
    """
    cfg: dict[str, Any] = {
        "purchase_price": st.column_config.NumberColumn("Purchase €", format="€%.2f"),
        "sale_price":     st.column_config.NumberColumn("Sale €",     format="€%.2f"),
        "markup":         st.column_config.NumberColumn("Markup €",   format="€%.2f"),
        "profit":         st.column_config.NumberColumn("Profit €",   format="€%.2f"),
        "roi":            st.column_config.NumberColumn("ROI %",      format="%.1f%%"),
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


def format_money(v: float | None) -> str:
    """Format *v* as a Euro money string, or '—' if not available."""
    return f"€{v:,.2f}" if pd.notna(v) else "—"  # type: ignore[arg-type]


def format_pct(v: float | None) -> str:
    """Format *v* as a percentage string, or '—' if not available."""
    return f"{v:.1f}%" if pd.notna(v) else "—"  # type: ignore[arg-type]


def delta_money(curr: float | None, prev: float | None) -> str | None:
    """Return a signed delta string like '€+12.50', or None if either value is NaN."""
    if pd.notna(curr) and pd.notna(prev):  # type: ignore[arg-type]
        return f"€{curr - prev:+,.2f}"  # type: ignore[operator]
    return None
