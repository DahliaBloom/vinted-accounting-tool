"""Warehouse tab: inventory editor, order display, and welcome state."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from streamlit_extras.dataframe_explorer import dataframe_explorer

from ui import STATUS_BADGE, accent_bar, format_money, money_column_config, TEAL, ACCENT
from utils import (
    CATEGORY_LABELS,
    DATE_COLS_ITEMS,
    GRADE_OPTIONS,
    ITEMS_KEY,
    ITEMS_SCHEMA,
    ORDERS_KEY,
    STATUS_OPTIONS,
    NO_ORDER_SENTINEL,
    apply_automation,
    coerce_items,
    coerce_orders,
    compute_derived,
    df_to_storage,
    get_config_options,
    has_changed,
    next_order_id,
    next_sku,
    norm_dates,
    sort_items_default,
)

# Maps a status to which date field should default to today when adding an item.
_STATUS_DATE_FIELD: dict[str, str] = {
    "Listed":      "listed_on",
    "Sold":        "sold_on",
    "Cancelled":   "cancelled_on",
}


# ---------------------------------------------------------------------------
# Add Item action
# ---------------------------------------------------------------------------


def _add_item(storage: object, context_status: str = "Pending") -> None:
    """Prepend a new item row pre-filled for *context_status* and persist."""
    today_str = date.today().isoformat()
    date_field = _STATUS_DATE_FIELD.get(context_status, "")
    row = {
        "sku":            next_sku(st.session_state.items_df),
        "status":         context_status,
        "brand":          "",
        "type":           "",
        "style":          "",
        "grade":          "",
        "origin":         "",
        "supplier":       "",
        "purchase_price": 0.0,
        "sale_price":     0.0,
        "push_cost":      0.0,
        "markup":         float("nan"),
        "profit":         float("nan"),
        "roi":            float("nan"),
        "listed_on":      today_str if date_field == "listed_on" else "",
        "sold_on":        today_str if date_field == "sold_on" else "",
        "cancelled_on":   today_str if date_field == "cancelled_on" else "",
        "order_id":       NO_ORDER_SENTINEL,
    }
    new_df = coerce_items(
        pd.concat([pd.DataFrame([row]), st.session_state.items_df], ignore_index=True)
    )
    st.session_state.items_df = new_df
    storage[ITEMS_KEY] = df_to_storage(new_df)  # type: ignore[index]
    st.rerun()


# ---------------------------------------------------------------------------
# Add Order dialog
# ---------------------------------------------------------------------------


@st.dialog(":material/shopping_cart: New Order", width="large")
def _add_order_dialog(storage: object) -> None:
    """Modal dialog for creating a bulk order with auto-generated items."""
    with st.container(border=True):
        accent_bar(TEAL)
        st.caption("Pricing")
        oc1, oc2, oc3, oc4 = st.columns([2, 2, 1, 2], vertical_alignment="bottom")
        ord_qty   = oc1.number_input("Quantity",         min_value=1,   value=1, step=1, key="dlg_order_qty")
        ord_total = oc2.number_input("Total Purchase €", min_value=0.0, format="%.2f",   key="dlg_order_total")
        price_per_item = ord_total / ord_qty if ord_qty > 0 else 0.0
        oc3.metric("Per item", f"€{price_per_item:.2f}")
        ord_note  = oc4.text_input("Note (optional)", key="dlg_order_note")

    with st.container(border=True):
        accent_bar(ACCENT)
        st.caption("Categories — toggle Divers when items in this order are mixed")
        order_vals: dict[str, str] = {}
        for cat in CATEGORY_LABELS:
            c_name, c_tog, c_sel = st.columns([2, 2, 6], vertical_alignment="center")
            c_name.markdown(f"**{cat.title()}**")
            divers = c_tog.toggle(
                "Divers", key=f"dlg_ord_div_{cat}",
                label_visibility="collapsed",
                help=f"Toggle if {cat} varies across items in this order",
            )
            if divers:
                c_sel.caption(f"*Mixed {cat} — will not be applied to individual items*")
                order_vals[cat] = ""
            else:
                order_vals[cat] = "|".join(
                    c_sel.multiselect(
                        cat.title(),
                        get_config_options(st.session_state.config_df, cat),
                        key=f"dlg_ord_ms_{cat}",
                        label_visibility="collapsed",
                    )
                )

    if st.button(
        "Create Order", type="primary",
        icon=":material/add_shopping_cart:", key="dlg_order_submit", width="stretch",
    ):
        order_id = next_order_id(st.session_state.orders_df)
        today_str = date.today().isoformat()
        new_items: list[dict] = []
        cur_sku = next_sku(st.session_state.items_df)
        sku_list: list[str] = []

        for _ in range(int(ord_qty)):
            new_items.append({
                "sku":            cur_sku,
                "status":         "In Shipping",
                "brand":          order_vals["brand"],
                "type":           order_vals["type"],
                "style":          order_vals["style"],
                "grade":          "",
                "origin":         order_vals["origin"],
                "supplier":       order_vals["supplier"],
                "purchase_price": price_per_item,
                "sale_price":     0.0,
                "push_cost":      0.0,
                "markup":         float("nan"),
                "profit":         float("nan"),
                "roi":            float("nan"),
                "listed_on":      "",
                "sold_on":        "",
                "cancelled_on":   "",
                "order_id":       order_id,
            })
            sku_list.append(str(cur_sku))
            cur_sku += 1

        st.session_state.orders_df = coerce_orders(pd.concat(
            [st.session_state.orders_df,
             pd.DataFrame([{
                 "order_id":       order_id,
                 "item_skus":      "|".join(sku_list),
                 "quantity":       int(ord_qty),
                 **{k: order_vals[k] for k in CATEGORY_LABELS},
                 "total_purchase": ord_total,
                 "price_per_item": price_per_item,
                 "note":           ord_note,
                 "created_on":     today_str,
             }])],
            ignore_index=True,
        ))
        storage[ORDERS_KEY] = df_to_storage(st.session_state.orders_df)  # type: ignore[index]

        new_items_df = coerce_items(pd.DataFrame(new_items))
        st.session_state.items_df = coerce_items(
            pd.concat([new_items_df, st.session_state.items_df], ignore_index=True)
        )
        storage[ITEMS_KEY] = df_to_storage(st.session_state.items_df)  # type: ignore[index]

        st.success(
            f":material/check_circle: Order #{order_id} created — "
            f"{int(ord_qty)} items (SKU {sku_list[0]}–{sku_list[-1]})."
        )
        st.rerun()


# ---------------------------------------------------------------------------
# Inventory editor
# ---------------------------------------------------------------------------


def _inventory_editor(
    subset_df: pd.DataFrame,
    editor_key: str,
    storage: object,
    context_status: str = "Pending",
) -> None:  # noqa: C901
    """Render action buttons + data_editor for *subset_df* and persist any changes.

    *context_status* controls which status (and matching date) is pre-filled when
    the "Add Item" button is clicked from this particular sub-tab.
    """
    # Buttons sit directly above the dataframe regardless of whether the tab is empty.
    btn_c1, btn_c2 = st.columns(2)
    if btn_c1.button(
        "Add Item",
        icon=":material/add_circle:",
        type="primary",
        key=f"{editor_key}_btn_add_item",
        width="stretch",
    ):
        _add_item(storage, context_status=context_status)
    if btn_c2.button(
        "Add Order",
        icon=":material/shopping_cart:",
        key=f"{editor_key}_btn_add_order",
        width="stretch",
    ):
        _add_order_dialog(storage)

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

    # Column config default values reflect the current tab's context so that
    # rows added inline via the editor's built-in "+" row also get sensible defaults.
    date_field = _STATUS_DATE_FIELD.get(context_status, "")
    today = date.today()

    edited = st.data_editor(
        _explored, key=editor_key, hide_index=True,
        num_rows="dynamic", width="stretch",
        column_order=col_order,
        column_config={
            **money_column_config(
                markup=st.column_config.NumberColumn("Markup €", format="€%.2f", disabled=True),
                profit=st.column_config.NumberColumn("Profit €", format="€%.2f", disabled=True),
                roi=st.column_config.NumberColumn("ROI %",       format="%.1f%%", disabled=True),
                purchase_price=st.column_config.NumberColumn("Purchase €", format="€%.2f", min_value=0.0, default=0.0),
                sale_price=st.column_config.NumberColumn("Sale €",         format="€%.2f", min_value=0.0, default=0.0),
            ),
            "sku":          st.column_config.NumberColumn("SKU", step=1),
            "status":       st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS, default=context_status),
            "push_cost":    st.column_config.NumberColumn("Push €", format="€%.2f", min_value=0.0, default=0.0),
            "listed_on":    st.column_config.DateColumn("Listed On",     default=today if date_field == "listed_on"     else None),
            "sold_on":      st.column_config.DateColumn("Sold On",       default=today if date_field == "sold_on"       else None),
            "cancelled_on": st.column_config.DateColumn("Cancelled On",  default=today if date_field == "cancelled_on"  else None),
            "days_tracker": st.column_config.TextColumn("Days", disabled=True),
            "grade":        st.column_config.SelectboxColumn("Grade", options=GRADE_OPTIONS),
            "brand":        st.column_config.TextColumn("Brand(s)"),
            "type":         st.column_config.TextColumn("Type(s)"),
            "style":        st.column_config.TextColumn("Style(s)"),
            "origin":       st.column_config.TextColumn("Origin"),
            "supplier":     st.column_config.TextColumn("Supplier"),
            "order_id":     st.column_config.NumberColumn("Order", default=NO_ORDER_SENTINEL),
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


# ---------------------------------------------------------------------------
# Orders sub-tab
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------


def render(storage: object) -> None:  # noqa: C901
    """Render the Warehouse tab."""
    items_df = st.session_state.items_df

    if items_df.empty:
        with st.container(border=True):
            st.markdown("### Welcome to your Vinted Tracker")
            st.caption("No items yet. Add your first item individually or create an order to get started.")
            ec1, ec2 = st.columns(2)
            if ec1.button(
                ":material/add_circle: Add Item", type="primary", width="stretch",
                key="welcome_add_item",
            ):
                _add_item(storage)
            if ec2.button(
                ":material/shopping_cart: Add Order", width="stretch",
                key="welcome_add_order",
            ):
                _add_order_dialog(storage)
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
            _inventory_editor(sort_items_default(items_df), "inv_all", storage, context_status="Pending")

    with sub_shipping:
        if sub_shipping.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "In Shipping"]),
                "inv_shipping", storage, context_status="In Shipping",
            )

    with sub_pending:
        if sub_pending.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Pending"]),
                "inv_pending", storage, context_status="Pending",
            )

    with sub_listed:
        if sub_listed.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Listed"]),
                "inv_listed", storage, context_status="Listed",
            )

    with sub_sold:
        if sub_sold.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Sold"]),
                "inv_sold", storage, context_status="Sold",
            )

    with sub_cancelled:
        if sub_cancelled.open:
            _inventory_editor(
                sort_items_default(items_df[items_df["status"] == "Cancelled"]),
                "inv_cancelled", storage, context_status="Cancelled",
            )

    with sub_orders:
        if sub_orders.open:
            _render_orders(items_df)
