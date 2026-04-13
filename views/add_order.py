"""Add Order tab: form for creating a bulk order with auto-generated items."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from ui import ACCENT, TEAL, accent_bar
from utils import (
    CATEGORY_LABELS,
    ITEMS_KEY,
    ORDERS_KEY,
    coerce_items,
    coerce_orders,
    df_to_storage,
    get_config_options,
    next_order_id,
    next_sku,
)


def render(storage: object) -> None:
    """Render the Add Order tab."""
    st.markdown("### :material/shopping_cart: New Order")

    with st.container(border=True):
        accent_bar(TEAL)
        st.caption("Pricing")
        oc1, oc2, oc3, oc4 = st.columns([2, 2, 1, 2], vertical_alignment="bottom")
        ord_qty   = oc1.number_input("Quantity",         min_value=1,   value=1, step=1, key="order_qty")
        ord_total = oc2.number_input("Total Purchase €", min_value=0.0, format="%.2f",   key="order_total")
        price_per_item = ord_total / ord_qty if ord_qty > 0 else 0.0
        oc3.metric("Per item", f"€{price_per_item:.2f}")
        ord_note  = oc4.text_input("Note (optional)", key="order_note")

    with st.container(border=True):
        accent_bar(ACCENT)
        st.caption("Categories — toggle Divers when items in this order are mixed")
        order_vals: dict[str, str] = {}
        for cat in CATEGORY_LABELS:
            c_name, c_tog, c_sel = st.columns([2, 2, 6], vertical_alignment="center")
            c_name.markdown(f"**{cat.title()}**")
            divers = c_tog.toggle(
                "Divers", key=f"ord_div_{cat}",
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
                        key=f"ord_ms_{cat}",
                        label_visibility="collapsed",
                    )
                )

    if st.button(
        "Create Order", type="primary",
        icon=":material/add_shopping_cart:", key="order_submit", width="stretch",
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

        st.session_state.items_df = coerce_items(pd.concat(
            [st.session_state.items_df, pd.DataFrame(new_items)], ignore_index=True,
        ))
        storage[ITEMS_KEY] = df_to_storage(st.session_state.items_df)  # type: ignore[index]

        st.success(
            f":material/check_circle: Order #{order_id} created — "
            f"{int(ord_qty)} items (SKU {sku_list[0]}–{sku_list[-1]})."
        )
        st.rerun()
