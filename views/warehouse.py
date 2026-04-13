"""Warehouse tab: inventory editor, order display, and welcome state."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_extras.dataframe_explorer import dataframe_explorer

from ui import STATUS_BADGE, format_money, money_column_config
from utils import (
    DATE_COLS_ITEMS,
    GRADE_OPTIONS,
    ITEMS_KEY,
    ITEMS_SCHEMA,
    STATUS_OPTIONS,
    apply_automation,
    coerce_items,
    coerce_orders,
    compute_derived,
    df_to_storage,
    has_changed,
    norm_dates,
    sort_items_default,
)

# Tab labels used for welcome-button deep links (must match app.py's st.tabs labels).
_TAB_ADD_ITEM  = ":material/add_circle: Add Item"
_TAB_ADD_ORDER = ":material/shopping_cart: Add Order"


def _request_add_item() -> None:
    """on_click callback: runs in Streamlit's callback phase, before the script body.
    At that point st.tabs() has not yet been called, so main_tabs is not yet
    widget-owned and can be set freely.
    """
    st.session_state.main_tabs = _TAB_ADD_ITEM


def _request_add_order() -> None:
    """on_click callback: same as above for the Add Order tab."""
    st.session_state.main_tabs = _TAB_ADD_ORDER


def _inventory_editor(
    subset_df: pd.DataFrame,
    editor_key: str,
    storage: object,
) -> None:  # noqa: C901
    """Render a data_editor for *subset_df* and persist any changes."""
    if subset_df.empty:
        st.info("No items in this view.")
        return

    display = compute_derived(coerce_items(subset_df))
    display.reset_index(drop=True, inplace=True)

    for dc in DATE_COLS_ITEMS:
        display[dc] = pd.to_datetime(display[dc], errors="coerce")

    _explored = dataframe_explorer(display, case=False)

    col_order = [
        "sku", "status", "brand", "type", "style", "grade",
        "origin", "supplier", "purchase_price", "sale_price",
        "push_cost", "markup", "profit", "roi", "days_tracker",
        "listed_on", "sold_on", "cancelled_on", "order_id",
    ]

    edited = st.data_editor(
        _explored, key=editor_key, hide_index=True,
        num_rows="dynamic", width="stretch",
        column_order=col_order,
        column_config={
            **money_column_config(
                markup=st.column_config.NumberColumn("Markup €", format="€%.2f", disabled=True),
                profit=st.column_config.NumberColumn("Profit €", format="€%.2f", disabled=True),
                roi=st.column_config.NumberColumn("ROI %",       format="%.1f%%", disabled=True),
                purchase_price=st.column_config.NumberColumn("Purchase €", format="€%.2f", min_value=0.0),
                sale_price=st.column_config.NumberColumn("Sale €",         format="€%.2f", min_value=0.0),
            ),
            "sku":          st.column_config.NumberColumn("SKU", step=1),
            "status":       st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
            "push_cost":    st.column_config.NumberColumn("Push €", format="€%.2f", min_value=0.0),
            "listed_on":    st.column_config.DateColumn("Listed On"),
            "sold_on":      st.column_config.DateColumn("Sold On"),
            "cancelled_on": st.column_config.DateColumn("Cancelled On"),
            "days_tracker": st.column_config.TextColumn("Days", disabled=True),
            "grade":        st.column_config.SelectboxColumn("Grade", options=GRADE_OPTIONS),
            "brand":        st.column_config.TextColumn("Brand(s)"),
            "type":         st.column_config.TextColumn("Type(s)"),
            "style":        st.column_config.TextColumn("Style(s)"),
            "origin":       st.column_config.TextColumn("Origin"),
            "supplier":     st.column_config.TextColumn("Supplier"),
            "order_id":     st.column_config.NumberColumn("Order"),
        },
        disabled=["markup", "profit", "roi", "days_tracker"],
    )

    # Process edits
    processed = edited.drop(columns=["days_tracker"], errors="ignore")
    processed = norm_dates(processed)
    for col in ITEMS_SCHEMA:
        if col not in processed.columns:
            processed[col] = "" if col in DATE_COLS_ITEMS else 0
    processed = processed[ITEMS_SCHEMA]

    rows = [apply_automation(r) for r in processed.to_dict("records")]
    processed = (
        pd.DataFrame(rows, columns=ITEMS_SCHEMA) if rows
        else pd.DataFrame(columns=ITEMS_SCHEMA)
    )
    processed = coerce_items(processed)

    original_skus = set(subset_df["sku"].astype(int).tolist())
    remaining = st.session_state.items_df[
        ~st.session_state.items_df["sku"].astype(int).isin(original_skus)
    ]
    updated = coerce_items(pd.concat([remaining, processed], ignore_index=True))
    current = st.session_state.items_df

    if has_changed(current, updated, sort_col="sku"):
        st.session_state.items_df = updated
        storage[ITEMS_KEY] = df_to_storage(updated)  # type: ignore[index]
        st.rerun()


def _render_orders(items_df: pd.DataFrame) -> None:
    """Render the Orders sub-tab (read-only order cards with child item details)."""
    orders_df = coerce_orders(st.session_state.orders_df)
    if orders_df.empty:
        st.info("No orders yet.")
        return

    for _, orow in orders_df.sort_values("order_id", ascending=False).iterrows():
        label = (
            f"Order #{int(orow['order_id'])} — "
            f"{int(orow['quantity'])} item(s) — "
            f"{format_money(orow['total_purchase'])} total "
            f"({format_money(orow['price_per_item'])}/item) — "
            f"{orow.get('created_on', '')}"
        )
        with st.expander(label):
            m1, m2, m3, m4 = st.columns(4)
            m1.markdown(f"**Origin:** {orow.get('origin') or '—'}")
            m2.markdown(f"**Supplier:** {orow.get('supplier') or '—'}")
            m3.markdown(f"**Brand:** {orow.get('brand') or '—'}")
            m4.markdown(f"**Type:** {orow.get('type') or '—'}")
            if orow.get("note"):
                st.caption(f"Note: {orow['note']}")

            child_str = str(orow.get("item_skus", ""))
            if child_str:
                try:
                    child_skus = [int(s.strip()) for s in child_str.split("|") if s.strip()]
                    child_items = items_df[items_df["sku"].isin(child_skus)]
                    if not child_items.empty:
                        cd = compute_derived(coerce_items(child_items))
                        st.dataframe(
                            cd[["sku", "status", "brand", "grade",
                                "purchase_price", "sale_price", "profit", "roi", "days_tracker"]],
                            width="stretch", hide_index=True,
                            column_config=money_column_config(
                                days_tracker=st.column_config.TextColumn("Days"),
                            ),
                        )
                except (ValueError, TypeError):
                    st.warning(f"Could not parse item SKUs for order #{int(orow['order_id'])}: {child_str}")


def render(storage: object) -> None:  # noqa: C901
    """Render the Warehouse tab."""
    items_df = st.session_state.items_df

    if items_df.empty:
        with st.container(border=True):
            st.markdown("### Welcome to your Vinted Tracker")
            st.caption("No items yet. Add your first item individually or create an order to get started.")
            ec1, ec2 = st.columns(2)
            ec1.button(
                ":material/add_circle: Add Item", type="primary", width="stretch",
                on_click=_request_add_item,
            )
            ec2.button(
                ":material/shopping_cart: Add Order", width="stretch",
                on_click=_request_add_order,
            )
        return

    # Build sub-tab labels with live counts from STATUS_BADGE
    counts = items_df["status"].value_counts()
    counts["All Items"] = counts.sum()
    tab_labels = [
        f"{icon} {status}  {int(counts.get(status, 0))}"
        for status, (_, icon) in STATUS_BADGE.items()
    ]

    (
        sub_all, sub_shipping, sub_pending,
        sub_listed, sub_sold, sub_cancelled, sub_orders,
    ) = st.tabs([*tab_labels, ":material/package_2: Orders"], on_change="rerun", key="inv_subtabs")

    with sub_all:
        if sub_all.open:
            _inventory_editor(sort_items_default(items_df), "inv_all", storage)

    with sub_shipping:
        if sub_shipping.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "In Shipping"]),
                "inv_shipping", storage,
            )

    with sub_pending:
        if sub_pending.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Pending"]),
                "inv_pending", storage,
            )

    with sub_listed:
        if sub_listed.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Listed"]),
                "inv_listed", storage,
            )

    with sub_sold:
        if sub_sold.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Sold"]),
                "inv_sold", storage,
            )

    with sub_cancelled:
        if sub_cancelled.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Cancelled"]),
                "inv_cancelled", storage,
            )

    with sub_orders:
        if sub_orders.open:
            _render_orders(items_df)
