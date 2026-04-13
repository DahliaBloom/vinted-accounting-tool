"""Vinted Accounting Tool — entry point.

Responsibilities: page config, localStorage init, session-state bootstrap,
CSS injection, and tab routing. All domain logic lives in utils.py,
all UI helpers in ui.py, and all tab content in views/.
"""

import streamlit as st
from streamlit_extras.local_storage_manager import local_storage_manager

from ui import inject_custom_css
from utils import (
    CONFIG_KEY,
    CONFIG_SCHEMA,
    ITEMS_KEY,
    ITEMS_SCHEMA,
    ORDERS_KEY,
    ORDERS_SCHEMA,
    OVERHEAD_KEY,
    OVERHEAD_SCHEMA,
    coerce_items,
    coerce_orders,
    coerce_overhead,
    df_from_storage,
)
from views import add_item, add_order, finance, insights, lookup, warehouse

# ── Page configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Vinted Accounting Tool",
    page_icon=":material/shopping_bag_speed:",
)

# ── localStorage manager ───────────────────────────────────────────────────────
_storage = local_storage_manager(key="vinted_storage")
if not _storage.ready():
    st.stop()

# ── Session-state initialisation (runs once per browser session) ───────────────
if "items_df" not in st.session_state:
    st.session_state.items_df    = coerce_items(df_from_storage(_storage.get(ITEMS_KEY),    ITEMS_SCHEMA))
    st.session_state.orders_df   = coerce_orders(df_from_storage(_storage.get(ORDERS_KEY),   ORDERS_SCHEMA))
    st.session_state.overhead_df = coerce_overhead(df_from_storage(_storage.get(OVERHEAD_KEY), OVERHEAD_SCHEMA))
    st.session_state.config_df   = df_from_storage(_storage.get(CONFIG_KEY), CONFIG_SCHEMA)

# ── Global CSS ─────────────────────────────────────────────────────────────────
inject_custom_css()

# ── Main tabs ──────────────────────────────────────────────────────────────────
tab_inv, tab_add, tab_order, tab_fin, tab_ins, tab_cfg = st.tabs(
    [
        ":material/warehouse: Warehouse",
        ":material/add_circle: Add Item",
        ":material/shopping_cart: Add Order",
        ":material/euro: Finance",
        ":material/insights: Insights",
        ":material/tune: Lookup",
    ],
    on_change="rerun",
    key="main_tabs",
)

with tab_inv:
    warehouse.render(_storage)

with tab_add:
    add_item.render(_storage)

with tab_order:
    add_order.render(_storage)

with tab_fin:
    finance.render(_storage)

with tab_ins:
    insights.render()

with tab_cfg:
    lookup.render(_storage)
