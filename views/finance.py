"""Finance tab: KPI dashboard, time-series charts, breakdowns, and overhead CRUD."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui import (
    ACCENT,
    EPOCH_START,
    GREEN,
    HISTOGRAM_BINS,
    MONTHLY_TREND_COUNT,
    ORANGE,
    PURPLE,
    RED,
    ROLLING_WINDOW_DAYS,
    TEAL,
    TOP_N_BREAKDOWN,
    accent_bar,
    delta_money,
    format_money,
    format_pct,
    revenue_profit_bar,
    style_fig,
)
from utils import (
    OVERHEAD_KEY,
    _to_iso,
    coerce_items,
    coerce_overhead,
    compute_derived,
    df_to_storage,
    explode_pipe_col,
    has_changed,
)


def _compute_period_kpis(
    items_f: pd.DataFrame,
    overhead: pd.DataFrame,
    d_from: pd.Timestamp,
    d_to: pd.Timestamp,
) -> dict:
    """Return a dict of all KPI values for the given period."""
    in_range = items_f[
        items_f["_listed"].between(d_from, d_to) | items_f["_sold"].between(d_from, d_to)
    ]
    sold_items = items_f[
        items_f["status"].isin(["Sold", "Cancelled"]) & items_f["_sold"].between(d_from, d_to)
    ]
    oh_range = overhead[overhead["_date"].between(d_from, d_to)]

    incidental     = oh_range["amount"].sum()
    item_spend     = in_range["purchase_price"].sum()
    push_spend     = in_range["push_cost"].sum()
    expenses       = item_spend + push_spend
    total_expenses = expenses + incidental
    revenue        = sold_items["sale_price"].sum()
    sold_pp_sum    = sold_items["purchase_price"].sum()
    real_profit    = revenue - sold_pp_sum
    net_profit     = revenue - total_expenses
    sold_count     = len(sold_items)

    total_roi  = (net_profit / total_expenses * 100) if total_expenses > 0 else float("nan")
    real_roi   = (real_profit / sold_pp_sum * 100)   if sold_pp_sum > 0    else float("nan")
    avg_rev    = revenue / sold_count     if sold_count else float("nan")
    avg_prof   = real_profit / sold_count if sold_count else float("nan")

    sold_der = compute_derived(sold_items) if not sold_items.empty else sold_items
    avg_roi_val = sold_der["roi"].mean()                  if not sold_der.empty  else float("nan")
    avg_pp_val  = in_range["purchase_price"].mean()       if not in_range.empty  else float("nan")
    avg_sp_val  = sold_items["sale_price"].mean()         if not sold_items.empty else float("nan")

    stock_value = items_f[
        ~items_f["status"].isin(["Sold", "Cancelled"])
    ]["purchase_price"].sum()

    days_in_range  = max((d_to.date() - d_from.date()).days + 1, 1)
    avg_sales_day  = sold_count / days_in_range

    return dict(
        in_range=in_range, sold_items=sold_items, oh_range=oh_range, sold_der=sold_der,
        incidental=incidental, item_spend=item_spend, push_spend=push_spend,
        expenses=expenses, total_expenses=total_expenses,
        revenue=revenue, sold_pp_sum=sold_pp_sum,
        real_profit=real_profit, net_profit=net_profit,
        total_roi=total_roi, real_roi=real_roi,
        avg_rev=avg_rev, avg_prof=avg_prof, avg_roi_val=avg_roi_val,
        avg_pp_val=avg_pp_val, avg_sp_val=avg_sp_val,
        stock_value=stock_value, sold_count=sold_count,
        avg_sales_day=avg_sales_day, days_in_range=days_in_range,
    )


def _render_kpi_cards(kpi: dict, prev: dict) -> None:
    with st.container(border=True):
        accent_bar(GREEN)
        st.caption("Revenue & Profit")
        k1 = st.columns(4)
        k1[0].metric("Revenue",     format_money(kpi["revenue"]),     delta_money(kpi["revenue"],     prev["revenue"]))
        k1[1].metric(
            "Real Profit",
            format_money(kpi["real_profit"]),
            delta_money(kpi["real_profit"], prev["real_profit"]),
        )
        k1[2].metric("Net Profit",  format_money(kpi["net_profit"]))
        k1[3].metric("Sales",       kpi["sold_count"], f"{kpi['sold_count'] - prev['sold_count']:+d}")

    with st.container(border=True):
        accent_bar(RED)
        st.caption("Expenses")
        k2 = st.columns(4)
        k2[0].metric("Total Expenses",   format_money(kpi["total_expenses"]))
        k2[1].metric("Item + Push Spend", format_money(kpi["expenses"]))
        k2[2].metric("Incidental Costs",  format_money(kpi["incidental"]))
        k2[3].metric("Stock Value",       format_money(kpi["stock_value"]))

    with st.container(border=True):
        accent_bar(PURPLE)
        st.caption("Returns")
        k3 = st.columns(4)
        k3[0].metric("Total ROI",       format_pct(kpi["total_roi"]))
        k3[1].metric("Real ROI",        format_pct(kpi["real_roi"]))
        k3[2].metric("Avg ROI / Sale",  format_pct(kpi["avg_roi_val"]))
        k3[3].metric("Avg Sales / Day", f"{kpi['avg_sales_day']:.2f}")

    with st.container(border=True):
        accent_bar(ACCENT)
        st.caption("Averages")
        k4 = st.columns(4)
        k4[0].metric("Avg Revenue / Sale", format_money(kpi["avg_rev"]))
        k4[1].metric("Avg Profit / Sale",  format_money(kpi["avg_prof"]))
        k4[2].metric("Avg Purchase Price", format_money(kpi["avg_pp_val"]))
        k4[3].metric("Avg Sale Price",     format_money(kpi["avg_sp_val"]))


def _render_time_series(kpi: dict, date_from: date, date_to: date) -> None:
    sold_items = kpi["sold_items"]
    in_range   = kpi["in_range"]
    oh_range   = kpi["oh_range"]

    if sold_items.empty and in_range.empty:
        st.info("No data in the selected date range yet. Expand the period or add items.")
        return

    sold_dated = sold_items.dropna(subset=["_sold"]) if not sold_items.empty else pd.DataFrame()
    ch1, ch2 = st.columns(2)
    if sold_items.empty and not in_range.empty:
        ch1.info("No sales yet in this period — stock value chart shown on the right.")

    if not sold_dated.empty:
        # 1. Revenue vs Expenses (cumulative)
        rev_cum = sold_dated.groupby("_sold")["sale_price"].sum().sort_index().cumsum()
        exp_parts: list[pd.DataFrame] = []
        if not in_range.empty:
            ie = in_range.copy()
            ie["_d"] = ie["_listed"].fillna(ie["_sold"])
            ie = ie.dropna(subset=["_d"])
            ie["_a"] = ie["purchase_price"] + ie["push_cost"]
            exp_parts.append(ie[["_d", "_a"]].rename(columns={"_d": "d", "_a": "a"}))
        if not oh_range.empty:
            exp_parts.append(oh_range[["_date", "amount"]].rename(columns={"_date": "d", "amount": "a"}))

        fig_re = go.Figure()
        fig_re.add_scatter(
            x=rev_cum.index, y=rev_cum.values, name="Revenue",
            mode="lines", line=dict(color=GREEN, width=2.5),
            fill="tozeroy", fillcolor="rgba(34,197,94,0.08)",
            hovertemplate="€%{y:,.2f}<extra>Revenue</extra>",
        )
        if exp_parts:
            ae = pd.concat(exp_parts, ignore_index=True)
            ec = ae.groupby("d")["a"].sum().sort_index().cumsum()
            fig_re.add_scatter(
                x=ec.index, y=ec.values, name="Expenses",
                mode="lines", line=dict(color=RED, width=2.5),
                hovertemplate="€%{y:,.2f}<extra>Expenses</extra>",
            )
        fig_re.update_layout(title="Revenue vs Expenses (Cumulative)")
        ch1.plotly_chart(style_fig(fig_re, money_y=True, date_x=True), width="stretch")

        # 2. Profit cumulative (real + net)
        sd2 = sold_dated.copy()
        sd2["_rp"] = sd2["sale_price"] - sd2["purchase_price"]
        sd2["_np"] = sd2["sale_price"] - sd2["purchase_price"] - sd2["push_cost"]
        rp_cum = sd2.groupby("_sold")["_rp"].sum().sort_index().cumsum()
        np_cum = sd2.groupby("_sold")["_np"].sum().sort_index().cumsum()
        fig_p = go.Figure()
        fig_p.add_scatter(
            x=rp_cum.index, y=rp_cum.values, name="Real Profit",
            mode="lines", line=dict(color=TEAL, width=2.5),
            fill="tozeroy", fillcolor="rgba(20,184,166,0.08)",
            hovertemplate="€%{y:,.2f}<extra>Real Profit</extra>",
        )
        fig_p.add_scatter(
            x=np_cum.index, y=np_cum.values, name="Net Profit",
            mode="lines", line=dict(color=ACCENT, width=2, dash="dot"),
            hovertemplate="€%{y:,.2f}<extra>Net Profit</extra>",
        )
        fig_p.update_layout(title="Profit Over Time (Cumulative)")
        ch2.plotly_chart(style_fig(fig_p, money_y=True, date_x=True, zero_line=True), width="stretch")

        # 3. ROI rolling average
        sold_der_chart = kpi["sold_der"].copy()
        if "_sold" not in sold_der_chart.columns:
            sold_der_chart["_sold"] = sold_items["_sold"]
        roi_d = sold_der_chart.dropna(subset=["roi", "_sold"])
        if not roi_d.empty:
            roi_s = (
                roi_d.groupby("_sold")["roi"].mean().sort_index()
                .rolling(ROLLING_WINDOW_DAYS, min_periods=1).mean().reset_index()
            )
            roi_s.columns = ["Date", "ROI"]
            fig_r = go.Figure()
            fig_r.add_scatter(
                x=roi_s["Date"], y=roi_s["ROI"], name="ROI",
                mode="lines", line=dict(color=PURPLE, width=2.5),
                fill="tozeroy", fillcolor="rgba(168,85,247,0.08)",
                hovertemplate=f"%{{y:.1f}}%<extra>{ROLLING_WINDOW_DAYS}-Day Avg ROI</extra>",
            )
            fig_r.update_layout(title=f"ROI ({ROLLING_WINDOW_DAYS}-Day Rolling Avg)")
            ch1.plotly_chart(style_fig(fig_r, pct_y=True, date_x=True, zero_line=True), width="stretch")

        # 4. Daily sales bar
        sc_d = sold_dated.groupby(sold_dated["_sold"].dt.date).size().reset_index(name="Count")
        sc_d.columns = ["Date", "Count"]
        fig_sc_bar = go.Figure()
        fig_sc_bar.add_bar(
            x=sc_d["Date"], y=sc_d["Count"], marker_color=ACCENT,
            hovertemplate="%{x|%b %d}: %{y} sales<extra></extra>",
        )
        fig_sc_bar.update_layout(title="Daily Sales Count")
        ch2.plotly_chart(style_fig(fig_sc_bar, date_x=True), width="stretch")

        # 5. Avg prices rolling
        asp = (
            sold_dated.groupby("_sold")["sale_price"].mean().sort_index()
            .rolling(ROLLING_WINDOW_DAYS, min_periods=1).mean()
        )
        fig_ap = go.Figure()
        fig_ap.add_scatter(
            x=asp.index, y=asp.values, name="Avg Sale Price",
            mode="lines", line=dict(color=GREEN, width=2.5),
            hovertemplate="€%{y:,.2f}<extra>Avg Sale Price</extra>",
        )
        avg_pp_series = (
            in_range.dropna(subset=["_listed"])
            .groupby("_listed")["purchase_price"].mean().sort_index()
            .rolling(ROLLING_WINDOW_DAYS, min_periods=1).mean()
        )
        if not avg_pp_series.empty:
            fig_ap.add_scatter(
                x=avg_pp_series.index, y=avg_pp_series.values, name="Avg Purchase Price",
                mode="lines", line=dict(color=ORANGE, width=2.5),
                hovertemplate="€%{y:,.2f}<extra>Avg Purchase Price</extra>",
            )
        fig_ap.update_layout(title=f"Avg Prices ({ROLLING_WINDOW_DAYS}-Day Rolling)")
        ch1.plotly_chart(style_fig(fig_ap, money_y=True, date_x=True), width="stretch")

    # 6. Stock value area (uses items_f from outer scope via kpi dict)
    items_f = kpi.get("_items_f")
    if items_f is not None:
        active = items_f[~items_f["status"].isin(["Sold", "Cancelled"])].dropna(subset=["_listed"])
        if not active.empty:
            sv_s = active.sort_values("_listed").copy()
            sv_s["_cv"] = sv_s["purchase_price"].cumsum()
            fig_sv = go.Figure()
            fig_sv.add_scatter(
                x=sv_s["_listed"], y=sv_s["_cv"], name="Stock Value",
                mode="lines", line=dict(color=TEAL, width=2.5),
                fill="tozeroy", fillcolor="rgba(20,184,166,0.10)",
                hovertemplate="€%{y:,.2f}<extra>Stock Value</extra>",
            )
            fig_sv.update_layout(title="Active Stock Value Over Time")
            target = ch2 if not sold_dated.empty else ch1
            target.plotly_chart(style_fig(fig_sv, money_y=True, date_x=True), width="stretch")


def _render_breakdowns(kpi: dict) -> None:
    sold_items = kpi["sold_items"]
    sold_der   = kpi["sold_der"]
    total_expenses = kpi["total_expenses"]
    item_spend     = kpi["item_spend"]
    push_spend     = kpi["push_spend"]
    incidental     = kpi["incidental"]

    # Waterfall: expense composition
    if total_expenses > 0:
        wf_vals = [item_spend, push_spend, incidental, total_expenses]
        wf_pcts = [
            f"€{v:,.0f}  ({v / total_expenses * 100:.0f}%)" if total_expenses > 0 else f"€{v:,.0f}"
            for v in wf_vals
        ]
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=["relative", "relative", "relative", "total"],
            x=["Item Spend", "Push Costs", "Incidental", "Total"],
            y=[item_spend, push_spend, incidental, 0],
            text=wf_pcts,
            textposition="outside",
            connector=dict(line=dict(color="rgba(99,122,182,0.25)", width=1, dash="dot")),
            increasing=dict(marker_color=RED),
            decreasing=dict(marker_color=GREEN),
            totals=dict(marker_color=ACCENT),
            hovertemplate="<b>%{x}</b><br>€%{y:,.2f}<extra></extra>",
        ))
        fig_wf.update_layout(title="Expense Composition (Waterfall)", uniformtext_minsize=9)
        st.plotly_chart(style_fig(fig_wf, money_y=True, height=300), width="stretch")
    else:
        st.info("No expenses in the selected period.")

    bd1, bd2 = st.columns(2)
    if not sold_items.empty:
        for col_obj, dim, title in [
            (bd1, "brand", f"Revenue by Brand (Top {TOP_N_BREAKDOWN})"),
            (bd2, "type",  "Revenue by Type"),
        ]:
            ex = explode_pipe_col(sold_items, dim)
            ex = ex[ex[dim].astype(str).ne("") & ex[dim].astype(str).ne("nan")]
            if not ex.empty:
                grp = ex.groupby(dim).agg(
                    Revenue=("sale_price", "sum"),
                    Profit=("profit",      "sum"),
                )
                col_obj.plotly_chart(
                    revenue_profit_bar(grp, title, height=340, top_n=TOP_N_BREAKDOWN),
                    width="stretch",
                )
            else:
                col_obj.info(f"No {dim} data.")
    else:
        st.info("No sold items in this period for breakdown charts.")

    # ROI histogram
    if not sold_der.empty and "roi" in sold_der.columns:
        roi_vals = sold_der["roi"].dropna()
        if len(roi_vals) > 1:
            mean_roi = roi_vals.mean()
            fig_hist = go.Figure()
            fig_hist.add_histogram(
                x=roi_vals, marker_color=PURPLE, opacity=0.8, nbinsx=HISTOGRAM_BINS,
                hovertemplate="ROI ~%{x:.0f}%: %{y} items<extra></extra>",
            )
            fig_hist.add_vline(x=0, line_dash="dot", line_color=RED, line_width=1.5,
                               annotation_text="Break-even", annotation_position="top right")
            fig_hist.add_vline(x=mean_roi, line_dash="dash", line_color=GREEN, line_width=1.5,
                               annotation_text=f"Avg {mean_roi:.1f}%",
                               annotation_position="top left")
            fig_hist.update_layout(title="ROI Distribution (Sold Items)",
                                   xaxis_title="ROI %", yaxis_title="Items")
            st.plotly_chart(style_fig(fig_hist, height=280), width="stretch")


def _render_comparisons(
    kpi: dict,
    prev: dict,
    date_from: date,
    date_to: date,
    prev_from_d: date,
    prev_to_d: date,
    items_f: pd.DataFrame,
) -> None:
    cmp1, cmp2 = st.columns(2)

    revenue, expenses, real_profit = kpi["revenue"], kpi["expenses"], kpi["real_profit"]
    prev_rev, prev_exp, prev_rp    = prev["revenue"], prev["expenses"], prev["real_profit"]

    if max(revenue, expenses, abs(real_profit), prev_rev, prev_exp, abs(prev_rp)) == 0:
        cmp1.info("No financial data in the selected period or its comparison window.")
    else:
        fig_cmp = go.Figure()
        metric_labels = ["Revenue", "Item+Push Spend", "Real Profit"]
        fig_cmp.add_bar(
            name=f"Current  ({date_from:%b %d}–{date_to:%b %d})",
            x=metric_labels, y=[revenue, expenses, real_profit],
            marker_color=[GREEN, ORANGE, TEAL],
            hovertemplate="%{x}: €%{y:,.2f}<extra>Current</extra>",
        )
        fig_cmp.add_bar(
            name=f"Previous ({prev_from_d:%b %d}–{prev_to_d:%b %d})",
            x=metric_labels, y=[prev_rev, prev_exp, prev_rp],
            marker_color=["rgba(34,197,94,0.45)", "rgba(249,115,22,0.45)", "rgba(20,184,166,0.45)"],
            hovertemplate="%{x}: €%{y:,.2f}<extra>Previous</extra>",
        )
        fig_cmp.update_layout(title="Current vs Previous Period", barmode="group", bargroupgap=0.12)
        cmp1.plotly_chart(style_fig(fig_cmp, money_y=True, zero_line=True), width="stretch")

    # Monthly trend (all-time, not period-filtered)
    hist_sold = items_f[
        items_f["status"].isin(["Sold", "Cancelled"]) & items_f["_sold"].notna()
    ].copy()

    if not hist_sold.empty:
        hist_sold = compute_derived(hist_sold)
        hist_sold["_month"] = hist_sold["_sold"].dt.to_period("M")
        monthly = (
            hist_sold.groupby("_month")
            .agg(Revenue=("sale_price", "sum"), Profit=("profit", "sum"))
            .tail(MONTHLY_TREND_COUNT)
        )
        monthly.index = monthly.index.astype(str)
        fig_mon = go.Figure()
        fig_mon.add_bar(
            x=monthly.index, y=monthly["Revenue"], name="Revenue",
            marker_color=GREEN,
            hovertemplate="%{x}: €%{y:,.2f}<extra>Revenue</extra>",
        )
        fig_mon.add_bar(
            x=monthly.index, y=monthly["Profit"], name="Profit",
            marker_color=TEAL,
            hovertemplate="%{x}: €%{y:,.2f}<extra>Profit</extra>",
        )
        fig_mon.update_layout(
            title=f"Monthly Revenue & Profit (Last {MONTHLY_TREND_COUNT} Months)",
            barmode="group",
        )
        cmp2.plotly_chart(style_fig(fig_mon, money_y=True, zero_line=True), width="stretch")
    else:
        cmp2.info("No historical sales data for monthly trend.")


def _render_overhead(today: date, storage: object) -> None:
    with st.expander(":material/receipt_long: Incidental Costs (Overhead)"):
        oh_c1, oh_c2, oh_c3, oh_c4 = st.columns([2, 3, 2, 1], vertical_alignment="bottom")
        overhead_amt  = oh_c1.number_input("Amount €",   min_value=0.0, format="%.2f", key="oh_amt")
        overhead_desc = oh_c2.text_input("Description",  key="oh_desc")
        overhead_dt   = oh_c3.date_input("Date",         value=today,   key="oh_dt")
        if oh_c4.button(":material/add:", key="oh_add", width="stretch") and overhead_amt > 0:
            st.session_state.overhead_df = pd.concat(
                [st.session_state.overhead_df,
                 pd.DataFrame([{
                     "date":        overhead_dt.isoformat(),
                     "amount":      overhead_amt,
                     "description": overhead_desc,
                 }])],
                ignore_index=True,
            )
            storage[OVERHEAD_KEY] = df_to_storage(st.session_state.overhead_df)  # type: ignore[index]
            st.rerun()

        if not st.session_state.overhead_df.empty:
            oh_display = (
                coerce_overhead(st.session_state.overhead_df)
                .sort_values("date", ascending=False)
                .reset_index(drop=True)
            )
            oh_display = oh_display.copy()
            oh_display["date"] = pd.to_datetime(oh_display["date"], errors="coerce")
            st.caption("Edit or delete rows directly in the table:")
            edited_oh = st.data_editor(
                oh_display, width="stretch", hide_index=True,
                num_rows="dynamic", key="oh_editor",
                column_config={
                    "amount":      st.column_config.NumberColumn("Amount €", format="€%.2f", min_value=0.0),
                    "date":        st.column_config.DateColumn("Date"),
                    "description": st.column_config.TextColumn("Description"),
                },
            )

            # Normalize both frames to detect real changes, avoiding brittle string comparison.
            def _normalize_oh(df: pd.DataFrame) -> pd.DataFrame:
                d = df.copy()
                d["date"]        = d["date"].apply(_to_iso)
                d["amount"]      = pd.to_numeric(d["amount"], errors="coerce").fillna(0.0)
                d["description"] = d["description"].fillna("").astype(str)
                return d.reset_index(drop=True)

            norm_before = _normalize_oh(oh_display)
            norm_after  = _normalize_oh(edited_oh)

            if has_changed(norm_before, norm_after):
                save_oh = edited_oh.copy()
                save_oh["date"]        = save_oh["date"].apply(_to_iso)
                save_oh["amount"]      = pd.to_numeric(save_oh["amount"], errors="coerce").fillna(0.0)
                save_oh["description"] = save_oh["description"].fillna("").astype(str)
                st.session_state.overhead_df = save_oh
                storage[OVERHEAD_KEY] = df_to_storage(save_oh)  # type: ignore[index]
                st.rerun()


def render(storage: object) -> None:
    """Render the Finance tab."""
    today       = date.today()
    first_this  = today.replace(day=1)
    lm_end      = first_this - timedelta(days=1)
    lm_start    = lm_end.replace(day=1)

    # ── Period selector ──────────────────────────────────────────────────────
    preset = st.pills(
        "Period",
        ["Last Month", "This Month", "This Year", "All Time", "Custom"],
        default="This Year", key="fin_preset",
    )
    preset = preset or "This Year"

    if preset == "Last Month":
        date_from, date_to = lm_start, lm_end
    elif preset == "This Month":
        date_from, date_to = first_this, today
    elif preset == "This Year":
        date_from, date_to = date(today.year, 1, 1), today
    elif preset == "All Time":
        date_from, date_to = EPOCH_START, today
    else:
        dc1, dc2 = st.columns(2)
        date_from = dc1.date_input("From", value=date(today.year, 1, 1), key="fin_d_from")
        date_to   = dc2.date_input("To",   value=today,                  key="fin_d_to")
        if date_from > date_to:
            st.warning("Start date is after end date — swapping automatically.")
            date_from, date_to = date_to, date_from

    d_from, d_to = pd.Timestamp(date_from), pd.Timestamp(date_to)

    # ── Prepare shared data ──────────────────────────────────────────────────
    items_f = coerce_items(st.session_state.items_df)
    items_f["_listed"] = pd.to_datetime(items_f["listed_on"], errors="coerce")
    items_f["_sold"]   = pd.to_datetime(items_f["sold_on"],   errors="coerce")

    overhead = coerce_overhead(st.session_state.overhead_df)
    overhead["_date"] = pd.to_datetime(overhead["date"], errors="coerce")

    # Current period KPIs
    kpi = _compute_period_kpis(items_f, overhead, d_from, d_to)
    kpi["_items_f"] = items_f  # pass through for stock-value chart

    # Previous period (same duration, immediately preceding)
    prev_to_d   = date_from - timedelta(days=1)
    prev_from_d = prev_to_d - timedelta(days=kpi["days_in_range"] - 1)
    p_from, p_to = pd.Timestamp(prev_from_d), pd.Timestamp(prev_to_d)
    prev_kpi = _compute_period_kpis(items_f, overhead, p_from, p_to)

    # ── KPI cards ────────────────────────────────────────────────────────────
    _render_kpi_cards(kpi, prev_kpi)

    # Last-month snapshot (expander — always shown, period-independent)
    lm_sold = items_f[
        items_f["status"].isin(["Sold", "Cancelled"])
        & items_f["_sold"].between(pd.Timestamp(lm_start), pd.Timestamp(lm_end))
    ]
    lm_oh  = overhead[overhead["_date"].between(pd.Timestamp(lm_start), pd.Timestamp(lm_end))]
    lm_rev = lm_sold["sale_price"].sum()
    lm_rp  = lm_rev - lm_sold["purchase_price"].sum()
    lm_in  = items_f[
        items_f["_listed"].between(pd.Timestamp(lm_start), pd.Timestamp(lm_end))
        | items_f["_sold"].between(pd.Timestamp(lm_start), pd.Timestamp(lm_end))
    ]
    lm_exp = lm_in["purchase_price"].sum() + lm_in["push_cost"].sum() + lm_oh["amount"].sum()

    with st.expander(f":material/calendar_month: Last month snapshot — {lm_start:%b %Y}"):
        lmc = st.columns(4)
        lmc[0].metric("Revenue",  format_money(lm_rev))
        lmc[1].metric("Expenses", format_money(lm_exp))
        lmc[2].metric("Profit",   format_money(lm_rp))
        lmc[3].metric("Sales",    len(lm_sold))

    # ── Chart sub-tabs ───────────────────────────────────────────────────────
    chart_ts, chart_bd, chart_cmp = st.tabs(
        [":material/show_chart: Time Series",
         ":material/bar_chart: Breakdowns",
         ":material/compare_arrows: Comparisons"],
        on_change="rerun", key="fin_chart_tabs",
    )

    with chart_ts:
        _render_time_series(kpi, date_from, date_to)

    with chart_bd:
        _render_breakdowns(kpi)

    with chart_cmp:
        _render_comparisons(kpi, prev_kpi, date_from, date_to, prev_from_d, prev_to_d, items_f)

    # ── Overhead CRUD ────────────────────────────────────────────────────────
    _render_overhead(today, storage)
