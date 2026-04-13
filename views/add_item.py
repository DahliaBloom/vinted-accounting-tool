"""Add Item tab: form for creating a single new inventory item."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import (
    GRADE_OPTIONS,
    ITEMS_KEY,
    NO_ORDER_SENTINEL,
    STATUS_OPTIONS,
    apply_automation,
    coerce_items,
    df_to_storage,
    get_config_options,
    next_sku,
)


def render(storage: object) -> None:
    """Render the Add Item tab."""
    cfg_df = st.session_state.config_df

    with st.container(border=True):
        st.markdown("### :material/add_circle: New Item")
        st.caption("SKU auto-increments. Derived values (Markup, Profit, ROI) are calculated automatically on save.")

        with st.form("add_item_form"):
            st.markdown("**Identity**")
            r1c1, r1c2, r1c3 = st.columns(3)
            ai_sku    = r1c1.number_input("SKU", value=next_sku(st.session_state.items_df), step=1)
            ai_status = r1c2.selectbox("Status", STATUS_OPTIONS)
            ai_grade  = r1c3.selectbox("Grade",  GRADE_OPTIONS)

            st.markdown("**Categorization**")
            r2c1, r2c2, r2c3 = st.columns(3)
            ai_brand = r2c1.multiselect("Brand", get_config_options(cfg_df, "brand"))
            ai_type  = r2c2.multiselect("Type",  get_config_options(cfg_df, "type"))
            ai_style = r2c3.multiselect("Style", get_config_options(cfg_df, "style"))
            r3c1, r3c2 = st.columns(2)
            ai_origin   = r3c1.multiselect("Origin",   get_config_options(cfg_df, "origin"))
            ai_supplier = r3c2.multiselect("Supplier", get_config_options(cfg_df, "supplier"))

            st.markdown("**Pricing**")
            r4c1, r4c2, r4c3 = st.columns(3)
            ai_pp = r4c1.number_input("Purchase Price €", min_value=0.0, format="%.2f")
            ai_sp = r4c2.number_input("Sale Price €",     min_value=0.0, format="%.2f", value=0.0)
            ai_pc = r4c3.number_input("Push Cost €",      min_value=0.0, format="%.2f", value=0.0)

            st.markdown("**Dates**")
            r5c1, r5c2 = st.columns(2)
            ai_listed = r5c1.date_input("Listed On", value=None)
            ai_sold   = r5c2.date_input("Sold On",   value=None)

            submitted = st.form_submit_button(
                "Add Item", icon=":material/add:", type="primary", width="stretch",
            )

    if submitted:
        row = {
            "sku":            int(ai_sku),
            "status":         ai_status,
            "brand":          "|".join(ai_brand),
            "type":           "|".join(ai_type),
            "style":          "|".join(ai_style),
            "grade":          ai_grade,
            "origin":         "|".join(ai_origin),
            "supplier":       "|".join(ai_supplier),
            "purchase_price": ai_pp,
            "sale_price":     ai_sp,
            "push_cost":      ai_pc,
            "markup":         0.0,
            "profit":         0.0,
            "roi":            0.0,
            "listed_on":      ai_listed.isoformat() if ai_listed else "",
            "sold_on":        ai_sold.isoformat()   if ai_sold   else "",
            "cancelled_on":   "",
            "order_id":       NO_ORDER_SENTINEL,
        }
        row = apply_automation(row)
        if int(ai_sku) in st.session_state.items_df["sku"].values:
            st.error(f"SKU {int(ai_sku)} already exists. Choose a different SKU.")
        else:
            new_df = coerce_items(pd.concat(
                [st.session_state.items_df, pd.DataFrame([row])], ignore_index=True,
            ))
            st.session_state.items_df = new_df
            storage[ITEMS_KEY] = df_to_storage(new_df)  # type: ignore[index]
            st.success(f":material/check_circle: Item SKU {int(ai_sku)} added.")
            st.rerun()
