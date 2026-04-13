"""Insights tab: dimension analysis, deep insights, and ideal item profile."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from ui import (
    ACCENT,
    AMBER,
    CHART_SEQ,
    HISTOGRAM_BINS,
    ORANGE,
    STATUS_COLORS,
    TEAL,
    TOP_N_DIMENSION,
    accent_bar,
    format_money,
    money_column_config,
    revenue_profit_bar,
    style_fig,
)
from utils import (
    STATUS_OPTIONS,
    coerce_items,
    compute_derived,
    explode_pipe_col,
)


def render() -> None:
    """Render the Insights tab."""
    today       = date.today()
    first_this  = today.replace(day=1)
    lm_end      = first_this - timedelta(days=1)
    lm_start    = lm_end.replace(day=1)

    all_items = coerce_items(st.session_state.items_df)
    closed    = all_items[all_items["status"].isin(["Sold", "Cancelled"])].copy()

    if closed.empty:
        with st.container(border=True):
            st.markdown("### No sales data yet")
            st.caption(
                "Insights unlock once you have sold or cancelled items. "
                "Add items and mark them as Sold to start seeing analytics."
            )
        return

    closed = compute_derived(closed)
    closed["_sold"] = pd.to_datetime(closed["sold_on"], errors="coerce")
    lm_mask   = closed["_sold"].between(pd.Timestamp(lm_start), pd.Timestamp(lm_end))
    closed_lm = closed[lm_mask]

    ins_period = st.pills(
        "Period", ["All Time", "Last Month"],
        default="All Time", key="ins_period",
    )
    ins_period = ins_period or "All Time"
    ins_data   = closed if ins_period == "All Time" else closed_lm

    dims = ["brand", "type", "style", "grade", "origin", "supplier"]

    # ── Performance by dimension (2×3 grid of bar charts) ───────────────────
    st.markdown("#### :material/trophy: Performance by Dimension")

    dim_pairs = [(dims[i], dims[i + 1]) for i in range(0, len(dims), 2)]
    for d1, d2 in dim_pairs:
        ic1, ic2 = st.columns(2)
        for col_obj, dim in [(ic1, d1), (ic2, d2)]:
            ex = explode_pipe_col(ins_data, dim) if dim != "grade" else ins_data.copy()
            ex = ex[ex[dim].astype(str).ne("") & ex[dim].astype(str).ne("nan")]
            if ex.empty:
                col_obj.info(f"No {dim} data for {ins_period}.")
                continue
            grp = ex.groupby(dim).agg(
                Revenue=("sale_price", "sum"),
                Profit=("profit",      "sum"),
            )
            col_obj.plotly_chart(
                revenue_profit_bar(grp, f"By {dim.title()} — {ins_period}", height=280),
                width="stretch",
            )

    # ── Deep Insights ────────────────────────────────────────────────────────
    st.markdown("#### :material/query_stats: Deep Insights")
    di1, di2 = st.columns(2)

    # Time-to-sell histogram
    sold_only = closed[closed["status"] == "Sold"].copy()
    sold_only["_ltd"] = pd.to_datetime(sold_only["listed_on"], errors="coerce")
    sold_only["_sld"] = pd.to_datetime(sold_only["sold_on"],   errors="coerce")
    sold_only["dts"]  = (sold_only["_sld"] - sold_only["_ltd"]).dt.days
    dts_clean = sold_only["dts"].dropna()
    dts_clean = dts_clean[dts_clean >= 0]

    if len(dts_clean) > 0:
        mean_dts = dts_clean.mean()
        fig_dts = go.Figure()
        fig_dts.add_histogram(
            x=dts_clean, marker_color=TEAL, opacity=0.85, nbinsx=HISTOGRAM_BINS,
            hovertemplate="%{x:.0f} days: %{y} items<extra></extra>",
        )
        fig_dts.add_vline(
            x=mean_dts, line_dash="dash", line_color=ORANGE, line_width=1.5,
            annotation_text=f"Avg {mean_dts:.1f}d",
            annotation_position="top right",
        )
        fig_dts.update_layout(
            title="Days to Sell (Listed → Sold)",
            xaxis_title="Days", yaxis_title="Items",
        )
        di1.plotly_chart(style_fig(fig_dts, height=280), width="stretch")
    else:
        di1.info("Need sold items with both listed and sold dates for this chart.")

    # Purchase vs Sale price scatter
    sc_data = closed[(closed["purchase_price"] > 0) & (closed["sale_price"] > 0)].copy()
    if not sc_data.empty:
        max_val   = max(sc_data["purchase_price"].max(), sc_data["sale_price"].max()) * 1.1
        has_grade = sc_data["grade"].astype(str).ne("").any()
        fig_sc = px.scatter(
            sc_data,
            x="purchase_price", y="sale_price",
            color="grade" if has_grade else None,
            color_discrete_sequence=CHART_SEQ,
            hover_name="sku",
            hover_data={"brand": True, "profit": ":.2f",
                        "purchase_price": False, "sale_price": False},
            labels={"purchase_price": "Purchase €", "sale_price": "Sale €"},
            title="Purchase vs Sale Price (dots above the line = profitable)",
        )
        fig_sc.add_scatter(
            x=[0, max_val], y=[0, max_val],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.22)", dash="dot", width=1),
            name="Break-even", showlegend=True, hoverinfo="skip",
        )
        di2.plotly_chart(
            style_fig(fig_sc, height=280, money_y=True, hovermode="closest"),
            width="stretch",
        )
    else:
        di2.info("Need items with both purchase and sale price for the scatter plot.")

    # ── Top 10 Most Profitable Items ─────────────────────────────────────────
    st.markdown("#### :material/format_list_numbered: Top 10 Most Profitable Items")
    top10 = closed.dropna(subset=["profit"]).sort_values("profit", ascending=False).head(10)
    if not top10.empty:
        t10_cols = ["sku", "brand", "type", "style", "grade",
                    "purchase_price", "sale_price", "markup", "profit", "roi"]
        st.dataframe(
            top10[[c for c in t10_cols if c in top10.columns]].reset_index(drop=True),
            width="stretch", hide_index=True,
            column_config=money_column_config(),
        )

    # ── Ideal Item ───────────────────────────────────────────────────────────
    st.markdown("#### :material/star: Ideal Item")

    ideal_profile: dict[str, str] = {}
    for dim in dims:
        ex = explode_pipe_col(closed, dim) if dim != "grade" else closed.copy()
        ex = ex[ex[dim].astype(str).ne("") & ex[dim].astype(str).ne("nan")]
        if ex.empty:
            continue
        grouped = ex.groupby(dim)["sale_price"].sum().dropna()
        if not grouped.empty:
            ideal_profile[dim] = grouped.idxmax()

    if ideal_profile:
        with st.container(border=True):
            accent_bar(AMBER)
            st.caption("Top value per dimension by total revenue — all time")
            badge_cols = st.columns(len(ideal_profile))
            for i, (dim, val) in enumerate(ideal_profile.items()):
                with badge_cols[i]:
                    st.badge(f"{dim.title()}: {val}", color="primary")

        with st.expander(":material/help: How is this determined?"):
            st.markdown(
                "For each dimension (Brand, Type, Style, Grade, Origin, Supplier), "
                "the value with the **highest total revenue** across all sold items "
                "is identified as the top performer. The **Ideal Item** is a real "
                "item in your history that matches all of these top values simultaneously. "
                "If none exists, the closest per-dimension matches are shown instead."
            )

        mask = pd.Series(True, index=closed.index)
        for dim, val in ideal_profile.items():
            mask &= closed[dim].astype(str).str.contains(val, regex=False, na=False)
        matches = closed[mask].sort_values("profit", ascending=False)

        if not matches.empty:
            st.success(f":material/check_circle: {len(matches)} item(s) match the ideal profile!")
            i_cols = ["sku", "brand", "type", "style", "grade", "origin", "supplier",
                      "purchase_price", "sale_price", "markup", "profit", "roi"]
            st.dataframe(
                matches[[c for c in i_cols if c in matches.columns]].reset_index(drop=True),
                width="stretch", hide_index=True,
                column_config=money_column_config(),
            )
        else:
            st.warning("No single item matches all top categories simultaneously.")
            for dim, val in ideal_profile.items():
                dm = closed[closed[dim].astype(str).str.contains(val, regex=False, na=False)]
                if not dm.empty:
                    best = dm.sort_values("sale_price", ascending=False).iloc[0]
                    st.caption(
                        f"**{dim.title()} = {val}:** "
                        f"{format_money(best['sale_price'])} revenue — SKU {int(best['sku'])}"
                    )
    else:
        # Fallback placeholder charts when no ideal profile can be built
        ic1, ic2 = st.columns(2)

        counts_inv = {s: int(all_items["status"].value_counts().get(s, 0)) for s in STATUS_OPTIONS}
        fig_d = go.Figure(go.Pie(
            values=list(counts_inv.values()),
            labels=list(counts_inv.keys()),
            hole=0.55,
            marker=dict(colors=[STATUS_COLORS[s] for s in STATUS_OPTIONS]),
            textinfo="label+value",
            textfont=dict(size=10),
            hovertemplate="%{label}: %{value}<extra></extra>",
        ))
        fig_d.update_layout(title="Items by Status", showlegend=False)
        ic1.plotly_chart(style_fig(fig_d, height=240), width="stretch")

        brand_ex = explode_pipe_col(all_items, "brand")
        brand_ex = brand_ex[brand_ex["brand"].astype(str).ne("") & brand_ex["brand"].astype(str).ne("nan")]
        if not brand_ex.empty:
            brand_cnt = brand_ex.groupby("brand").size().sort_values(ascending=True).tail(TOP_N_DIMENSION)
            fig_br = go.Figure()
            fig_br.add_bar(
                y=brand_cnt.index, x=brand_cnt.values, orientation="h",
                marker_color=ACCENT,
                hovertemplate="%{y}: %{x} items<extra></extra>",
            )
            fig_br.update_layout(
                title=f"Item Count by Brand (Top {TOP_N_DIMENSION})",
                yaxis_title="", xaxis_title="Items",
            )
            ic2.plotly_chart(style_fig(fig_br, height=240, hovermode="closest"), width="stretch")
        else:
            ic2.info("No brand data yet. Add brands via the Lookup tab.")

        st.info("Not enough data to determine an ideal item profile.")
