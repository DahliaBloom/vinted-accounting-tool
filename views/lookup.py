"""Lookup tab: manage dropdown options (brands, types, styles, etc.)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import ACCENT, TEAL, accent_bar
from utils import (
    CATEGORY_LABELS,
    CONFIG_KEY,
    ITEMS_KEY,
    ITEMS_SCHEMA,
    ORDERS_KEY,
    ORDERS_SCHEMA,
    OVERHEAD_KEY,
    OVERHEAD_SCHEMA,
    CONFIG_SCHEMA,
    coerce_items,
    coerce_orders,
    coerce_overhead,
    df_from_storage,
    df_to_storage,
    get_config_options,
)


def render(storage: object) -> None:
    """Render the Lookup Values tab."""
    st.markdown("### :material/tune: Lookup Values")
    st.caption(
        "Manage the dropdown options available when adding items and orders. "
        "Changes take effect immediately."
    )

    cfg_df = st.session_state.config_df

    # ── Add new value ────────────────────────────────────────────────────────
    with st.container(border=True):
        accent_bar(TEAL)
        st.caption("Add a new value")
        fa1, fa2, fa3 = st.columns([2, 3, 1], vertical_alignment="bottom")
        add_cat = fa1.selectbox("Category", CATEGORY_LABELS, key="cfg_add_cat")
        add_val = fa2.text_input(
            "Value", key="cfg_add_val",
            label_visibility="collapsed",
            placeholder=f"New {add_cat} value…",
        )
        if fa3.button("Add", type="primary", icon=":material/add:", key="cfg_add_btn", width="stretch"):
            if add_val.strip():
                existing = get_config_options(cfg_df, add_cat)
                if add_val.strip() in existing:
                    st.warning(f"**{add_val.strip()}** already exists in {add_cat}.")
                else:
                    st.session_state.config_df = pd.concat(
                        [cfg_df, pd.DataFrame([{"category": add_cat, "value": add_val.strip()}])],
                        ignore_index=True,
                    )
                    storage[CONFIG_KEY] = df_to_storage(st.session_state.config_df)  # type: ignore[index]
                    st.rerun()
            else:
                st.warning("Enter a value before clicking Add.")

    st.markdown("")

    # ── Current values — one card per category ───────────────────────────────
    cat_cols = st.columns(len(CATEGORY_LABELS), gap="small")
    for col_obj, cat in zip(cat_cols, CATEGORY_LABELS):
        with col_obj:
            with st.container(border=True):
                accent_bar(ACCENT)
                st.caption(cat.title())
                cfg_df = st.session_state.config_df  # re-read after any delete
                cat_vals = get_config_options(cfg_df, cat)
                if not cat_vals:
                    st.markdown("*No values yet*")
                else:
                    for val in cat_vals:
                        mask    = (cfg_df["category"] == cat) & (cfg_df["value"] == val)
                        row_idx = cfg_df[mask].index
                        v1, v2  = st.columns([5, 1], vertical_alignment="center")
                        v1.markdown(f"`{val}`")
                        if row_idx.size > 0:
                            if v2.button(
                                ":material/close:", key=f"del_{cat}_{val}",
                                width="stretch",
                            ):
                                st.session_state.config_df = (
                                    cfg_df.drop(row_idx).reset_index(drop=True)
                                )
                                storage[CONFIG_KEY] = df_to_storage(st.session_state.config_df)  # type: ignore[index]
                                st.rerun()

    # ── Danger zone ──────────────────────────────────────────────────────────
    st.markdown("---")
    with st.container(border=True):
        st.markdown("#### :material/warning: Danger Zone")
        st.caption(
            "Permanently deletes **all** items, orders, overhead entries, and lookup "
            "values stored in your browser. This cannot be undone."
        )

        if not st.session_state.get("_confirm_clear"):
            if st.button(
                ":material/delete_forever: Clear All Data",
                type="secondary",
                key="clear_data_btn",
            ):
                st.session_state["_confirm_clear"] = True
                st.rerun()
        else:
            st.warning("Are you sure? All data will be permanently deleted.")
            cc1, cc2 = st.columns(2)
            if cc1.button(
                ":material/delete_forever: Yes, delete everything",
                type="primary",
                key="clear_data_confirm",
                width="stretch",
            ):
                for key in (ITEMS_KEY, ORDERS_KEY, OVERHEAD_KEY, CONFIG_KEY):
                    storage[key] = []  # type: ignore[index]
                for ss_key in ("items_df", "orders_df", "overhead_df", "config_df"):
                    del st.session_state[ss_key]
                st.session_state.pop("_confirm_clear", None)
                st.rerun()
            if cc2.button("Cancel", key="clear_data_cancel", width="stretch"):
                st.session_state.pop("_confirm_clear", None)
                st.rerun()
