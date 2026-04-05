import os
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
import streamlit_authenticator as stauth

from utils import (
    load_data, save_data, next_sku, next_order_id,
    compute_derived, apply_automation, get_config_options,
    explode_pipe_col, coerce_items, coerce_orders, coerce_overhead,
    sort_items_default,
    ITEMS_SCHEMA, ORDERS_SCHEMA, OVERHEAD_SCHEMA, CONFIG_SCHEMA,
    STATUS_OPTIONS, GRADE_OPTIONS, DATE_COLS_ITEMS,
    STATUS_SORT, STATUS_BADGE, CATEGORY_LABELS,
)

# ── Page configuration ────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Vinted Accounting Tool",
    page_icon=":material/shopping_bag_speed:",
)

DATA_DIR = Path("data")
ITEMS_PATH = str(DATA_DIR / "items.csv")
ORDERS_PATH = str(DATA_DIR / "orders.csv")
OVERHEAD_PATH = str(DATA_DIR / "overhead.csv")
CONFIG_PATH = str(DATA_DIR / "config.csv")

# ── Colour palette ────────────────────────────────────────────────────────────
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

# ── Authentication setup ───────────────────────────────────────────────────────
load_dotenv()
_auth_user       = os.getenv("APP_USERNAME", "admin")
_auth_pass       = os.getenv("APP_PASSWORD", "changeme")
_auth_name       = os.getenv("APP_FIRST_NAME", "Admin")
_auth_cookie_key = os.getenv("APP_COOKIE_KEY", "fallback-insecure-key")

authenticator = stauth.Authenticate(
    credentials={
        "usernames": {
            _auth_user: {
                "first_name": _auth_name,
                "last_name":  "",
                "email":      "",
                "password":   _auth_pass,
            }
        }
    },
    cookie_name="vinted_tracker_session",
    cookie_key=_auth_cookie_key,
    cookie_expiry_days=30,
)

# ── Login gate — stop here if not authenticated ────────────────────────────────
try:
    authenticator.login(
        fields={"Form name": "Vinted Tracker", "Login": "Sign in"},
    )
except Exception as _auth_exc:
    st.error(str(_auth_exc))

_auth_status = st.session_state.get("authentication_status")
if _auth_status is False:
    st.error(":material/lock: Incorrect username or password.")
    st.stop()
elif _auth_status is None:
    st.stop()

# ── Session-state initialisation ──────────────────────────────────────────────
if "items_df" not in st.session_state:
    DATA_DIR.mkdir(exist_ok=True)
    st.session_state.items_df    = coerce_items(load_data(ITEMS_PATH,    ITEMS_SCHEMA))
    st.session_state.orders_df   = coerce_orders(load_data(ORDERS_PATH,   ORDERS_SCHEMA))
    st.session_state.overhead_df = coerce_overhead(load_data(OVERHEAD_PATH, OVERHEAD_SCHEMA))
    st.session_state.config_df   = load_data(CONFIG_PATH, CONFIG_SCHEMA)

# ── Global date helpers (computed once, used across all tabs) ─────────────────
_today      = date.today()
_first_this = _today.replace(day=1)
_lm_end     = _first_this - timedelta(days=1)
_lm_start   = _lm_end.replace(day=1)

# ── Global helpers ────────────────────────────────────────────────────────────

def _to_iso(val):
    try:
        if val is None or pd.isna(val):
            return ""
    except (ValueError, TypeError):
        pass
    if hasattr(val, "isoformat"):
        return val.isoformat()[:10]
    s = str(val).strip()
    return "" if s in ("", "NaT", "nan", "None") else s


def _norm_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in DATE_COLS_ITEMS:
        if c in df.columns:
            df[c] = df[c].apply(_to_iso)
    return df


def _fm(v):
    return f"€{v:,.2f}" if pd.notna(v) else "—"

def _fp(v):
    return f"{v:.1f}%" if pd.notna(v) else "—"

def _dm(curr, prev):
    if pd.notna(curr) and pd.notna(prev):
        return f"€{curr - prev:+,.2f}"
    return None


def _accent(color: str):
    """Inject a 3 px coloured accent bar — call as first element inside a bordered container."""
    st.html(
        f'<div style="height:3px;background:linear-gradient(90deg,{color}cc,transparent);'
        f'border-radius:4px;margin-bottom:6px"></div>'
    )


def _style_fig(
    fig,
    height: int = 320,
    money_y: bool = False,
    pct_y: bool = False,
    date_x: bool = False,
    zero_line: bool = False,
    hovermode: str = "x unified",
) -> go.Figure:
    """Dark-theme chart styling with optional axis formatting.

    Pass hovermode="closest" for horizontal bar / scatter charts where
    "x unified" would group by the numeric value axis instead of category.
    """
    yaxis_kw: dict = dict(
        gridcolor="rgba(99,122,182,0.10)",
        zerolinecolor="rgba(99,122,182,0.15)",
    )
    if money_y:
        yaxis_kw["tickprefix"] = "€"
    if pct_y:
        yaxis_kw["ticksuffix"] = "%"

    xaxis_kw: dict = dict(
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


# ── Custom CSS ────────────────────────────────────────────────────────────────
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


# ── Logout bar ────────────────────────────────────────────────────────────────
_lb1, _lb2 = st.columns([9, 1])
_lb1.caption(
    f":material/person: {st.session_state.get('name') or _auth_name}"
)
with _lb2:
    authenticator.logout("Sign out", "main", key="nav_logout")

# ── Main tabs ─────────────────────────────────────────────────────────────────
tab_inv, tab_add, tab_order, tab_fin, tab_ins, tab_cfg = st.tabs(
    [":material/inventory_2: Inventory",   ":material/add_circle: Add Item",
     ":material/shopping_cart: Add Order", ":material/euro: Finance",
     ":material/insights: Insights",       ":material/tune: Lookup Values"],
    on_change="rerun", key="main_tabs",
)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — INVENTORY
# ═════════════════════════════════════════════════════════════════════════════
with tab_inv:
    _items = st.session_state.items_df

    if _items.empty:
        with st.container(border=True):
            st.markdown("### Welcome to your Vinted Tracker")
            st.caption("No items yet. Add your first item individually or create an order to get started.")
            ec1, ec2 = st.columns(2)
            if ec1.button(":material/add_circle: Add Item", type="primary", width="stretch"):
                st.session_state.main_tabs = ":material/add_circle: Add Item"
                st.rerun()
            if ec2.button(":material/shopping_cart: Add Order", width="stretch"):
                st.session_state.main_tabs = ":material/shopping_cart: Add Order"
                st.rerun()
    else:
        # Status summary badges
        _cnts  = _items["status"].value_counts()
        bcols  = st.columns(len(STATUS_BADGE), gap="small")
        for i, (status, (btype, icon)) in enumerate(STATUS_BADGE.items()):
            with bcols[i]:
                st.badge(f"{status}  {int(_cnts.get(status, 0))}", color=btype, icon=icon)

        sub_all, sub_inv, sub_closed, sub_orders = st.tabs(
            ["All Items", "Active Inventory", "Closed", "Orders"],
            on_change="rerun", key="inv_subtabs",
        )

        # ── shared editor ─────────────────────────────────────────────────
        def _inventory_editor(subset_df: pd.DataFrame, editor_key: str):
            if subset_df.empty:
                st.info("No items in this view.")
                return

            display = compute_derived(coerce_items(subset_df))

            # Compact sort + search row
            sc1, sc2, sc3 = st.columns([3, 2, 2], gap="small")
            sortable = [c for c in display.columns if c != "days_tracker"]
            with sc1:
                sort_col = st.selectbox(
                    "Sort by", sortable,
                    index=sortable.index("status") if "status" in sortable else 0,
                    key=f"sort_{editor_key}",
                )
            with sc2:
                sort_dir = st.radio(
                    "Direction", ["↑ Asc", "↓ Desc"],
                    key=f"dir_{editor_key}", horizontal=True,
                    label_visibility="collapsed",
                )
            with sc3:
                search_term = st.text_input(
                    "Filter", placeholder="🔍 Filter rows…",
                    key=f"search_{editor_key}", label_visibility="collapsed",
                )

            asc = sort_dir == "↑ Asc"
            if sort_col == "status":
                display["_so"]  = display["status"].map(STATUS_SORT).fillna(5)
                display["_oid"] = display["order_id"].replace(-1, 999_999)
                display = display.sort_values(["_so", "_oid", "sku"], ascending=[asc, asc, asc])
                display.drop(columns=["_so", "_oid"], inplace=True)
            else:
                display = display.sort_values(sort_col, ascending=asc, na_position="last")
            display.reset_index(drop=True, inplace=True)

            # Mini summary
            _sub_c = coerce_items(subset_df)
            _sub_sold = _sub_c[_sub_c["status"] == "Sold"]
            _avg_roi_sub = (
                compute_derived(_sub_sold)["roi"].mean()
                if not _sub_sold.empty else float("nan")
            )
            with st.container(border=True):
                _accent(ACCENT)
                sm1, sm2, sm3, sm4 = st.columns(4)
                sm1.metric("Items",       len(subset_df))
                sm2.metric("Invested",    _fm(_sub_c["purchase_price"].sum()))
                sm3.metric("Avg Purchase",_fm(_sub_c["purchase_price"].mean()))
                sm4.metric("Avg ROI",     _fp(_avg_roi_sub))

            # Search → read-only mode
            if search_term.strip():
                mask = display.astype(str).apply(
                    lambda col: col.str.contains(search_term.strip(), case=False, na=False)
                ).any(axis=1)
                fv = display[mask].copy()
                st.caption(f"Showing {len(fv)} of {len(display)} rows — read-only while filtering")
                for dc in DATE_COLS_ITEMS:
                    fv[dc] = pd.to_datetime(fv[dc], errors="coerce")
                st.dataframe(fv, width="stretch", hide_index=True)
                return

            for dc in DATE_COLS_ITEMS:
                display[dc] = pd.to_datetime(display[dc], errors="coerce")

            col_order = [
                "sku", "status", "brand", "type", "style", "grade",
                "origin", "supplier", "purchase_price", "sale_price",
                "push_cost", "markup", "profit", "roi", "days_tracker",
                "listed_on", "sold_on", "cancelled_on", "order_id",
            ]

            edited = st.data_editor(
                display, key=editor_key, hide_index=True,
                num_rows="dynamic", width="stretch",
                column_order=col_order,
                column_config={
                    "sku":           st.column_config.NumberColumn("SKU", step=1),
                    "status":        st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
                    "purchase_price":st.column_config.NumberColumn("Purchase €",  format="€%.2f", min_value=0.0),
                    "sale_price":    st.column_config.NumberColumn("Sale €",       format="€%.2f", min_value=0.0),
                    "push_cost":     st.column_config.NumberColumn("Push €",       format="€%.2f", min_value=0.0),
                    "markup":        st.column_config.NumberColumn("Markup €",     format="€%.2f", disabled=True),
                    "profit":        st.column_config.NumberColumn("Profit €",     format="€%.2f", disabled=True),
                    "roi":           st.column_config.NumberColumn("ROI %",        format="%.1f%%", disabled=True),
                    "listed_on":     st.column_config.DateColumn("Listed On"),
                    "sold_on":       st.column_config.DateColumn("Sold On"),
                    "cancelled_on":  st.column_config.DateColumn("Cancelled On"),
                    "days_tracker":  st.column_config.TextColumn("Days", disabled=True),
                    "grade":         st.column_config.SelectboxColumn("Grade", options=GRADE_OPTIONS),
                    "brand":         st.column_config.TextColumn("Brand(s)"),
                    "type":          st.column_config.TextColumn("Type(s)"),
                    "style":         st.column_config.TextColumn("Style(s)"),
                    "origin":        st.column_config.TextColumn("Origin"),
                    "supplier":      st.column_config.TextColumn("Supplier"),
                    "order_id":      st.column_config.NumberColumn("Order"),
                },
                disabled=["markup", "profit", "roi", "days_tracker"],
            )

            # Process edits
            processed = edited.drop(columns=["days_tracker"], errors="ignore")
            processed = _norm_dates(processed)
            for col in ITEMS_SCHEMA:
                if col not in processed.columns:
                    processed[col] = "" if col in DATE_COLS_ITEMS else 0
            processed = processed[ITEMS_SCHEMA]

            rows = [apply_automation(r.to_dict()) for _, r in processed.iterrows()]
            processed = (
                pd.DataFrame(rows, columns=ITEMS_SCHEMA) if rows
                else pd.DataFrame(columns=ITEMS_SCHEMA)
            )
            processed = coerce_items(processed)

            original_skus = set(subset_df["sku"].astype(int).tolist())
            remaining     = st.session_state.items_df[
                ~st.session_state.items_df["sku"].astype(int).isin(original_skus)
            ]
            updated = coerce_items(pd.concat([remaining, processed], ignore_index=True))
            current = coerce_items(st.session_state.items_df)

            if (
                updated.shape != current.shape
                or not updated.sort_values("sku").reset_index(drop=True).astype(str).equals(
                    current.sort_values("sku").reset_index(drop=True).astype(str)
                )
            ):
                st.session_state.items_df = updated
                save_data(updated, ITEMS_PATH)
                st.rerun()

        # ── All Items ─────────────────────────────────────────────────────
        with sub_all:
            ic1, ic2 = st.columns(2)

            # Status donut
            counts_inv = {s: int(_items["status"].value_counts().get(s, 0)) for s in STATUS_OPTIONS}
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
            ic1.plotly_chart(_style_fig(fig_d, height=240), width="stretch")

            # Brand bar
            brand_ex = explode_pipe_col(_items, "brand")
            brand_ex = brand_ex[brand_ex["brand"].astype(str).ne("") & brand_ex["brand"].astype(str).ne("nan")]
            if not brand_ex.empty:
                brand_cnt = brand_ex.groupby("brand").size().sort_values(ascending=True).tail(10)
                fig_br = go.Figure()
                fig_br.add_bar(
                    y=brand_cnt.index, x=brand_cnt.values, orientation="h",
                    marker_color=ACCENT,
                    hovertemplate="%{y}: %{x} items<extra></extra>",
                )
                fig_br.update_layout(title="Item Count by Brand (Top 10)",
                                     yaxis_title="", xaxis_title="Items")
                ic2.plotly_chart(_style_fig(fig_br, height=240, hovermode="closest"), width="stretch")
            else:
                ic2.info("No brand data yet. Add brands via the sidebar lookup manager.")

            _inventory_editor(sort_items_default(_items), "inv_all")

        with sub_inv:
            _inventory_editor(
                sort_items_default(_items[_items["status"].isin(["Pending", "Listed"])]),
                "inv_active",
            )

        with sub_closed:
            _inventory_editor(
                sort_items_default(_items[_items["status"].isin(["Sold", "Cancelled"])]),
                "inv_closed",
            )

        with sub_orders:
            orders_df = coerce_orders(st.session_state.orders_df)
            if orders_df.empty:
                st.info("No orders yet.")
            else:
                for _, orow in orders_df.sort_values("order_id", ascending=False).iterrows():
                    label = (
                        f"Order #{int(orow['order_id'])} — "
                        f"{int(orow['quantity'])} item(s) — "
                        f"{_fm(orow['total_purchase'])} total "
                        f"({_fm(orow['price_per_item'])}/item) — "
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
                                child_items = _items[_items["sku"].isin(child_skus)]
                                if not child_items.empty:
                                    cd = compute_derived(coerce_items(child_items))
                                    st.dataframe(
                                        cd[["sku", "status", "brand", "grade",
                                            "purchase_price", "sale_price", "profit", "roi", "days_tracker"]],
                                        width="stretch", hide_index=True,
                                        column_config={
                                            "purchase_price": st.column_config.NumberColumn("Purchase €", format="€%.2f"),
                                            "sale_price":     st.column_config.NumberColumn("Sale €",     format="€%.2f"),
                                            "profit":         st.column_config.NumberColumn("Profit €",   format="€%.2f"),
                                            "roi":            st.column_config.NumberColumn("ROI",        format="%.1f%%"),
                                            "days_tracker":   st.column_config.TextColumn("Days"),
                                        },
                                    )
                            except (ValueError, TypeError):
                                pass


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — ADD ITEM
# ═════════════════════════════════════════════════════════════════════════════
with tab_add:
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
            "sku": int(ai_sku), "status": ai_status,
            "brand": "|".join(ai_brand), "type": "|".join(ai_type),
            "style": "|".join(ai_style), "grade": ai_grade,
            "origin": "|".join(ai_origin), "supplier": "|".join(ai_supplier),
            "purchase_price": ai_pp, "sale_price": ai_sp, "push_cost": ai_pc,
            "markup": 0.0, "profit": 0.0, "roi": 0.0,
            "listed_on":    ai_listed.isoformat() if ai_listed else "",
            "sold_on":      ai_sold.isoformat()   if ai_sold   else "",
            "cancelled_on": "", "order_id": -1,
        }
        row = apply_automation(row)
        if int(ai_sku) in st.session_state.items_df["sku"].values:
            st.error(f"SKU {int(ai_sku)} already exists. Choose a different SKU.")
        else:
            new_df = coerce_items(pd.concat(
                [st.session_state.items_df, pd.DataFrame([row])], ignore_index=True,
            ))
            st.session_state.items_df = new_df
            save_data(new_df, ITEMS_PATH)
            st.success(f":material/check_circle: Item SKU {int(ai_sku)} added.")
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — ADD ORDER
# ═════════════════════════════════════════════════════════════════════════════
with tab_order:
    st.markdown("### :material/shopping_cart: New Order")

    with st.container(border=True):
        _accent(TEAL)
        st.caption("Pricing")
        oc1, oc2, oc3, oc4 = st.columns([2, 2, 1, 2], vertical_alignment="bottom")
        ord_qty   = oc1.number_input("Quantity",         min_value=1,   value=1, step=1, key="order_qty")
        ord_total = oc2.number_input("Total Purchase €", min_value=0.0, format="%.2f",   key="order_total")
        ppi       = ord_total / ord_qty if ord_qty > 0 else 0.0
        oc3.metric("Per item", f"€{ppi:.2f}")
        ord_note  = oc4.text_input("Note (optional)", key="order_note")

    with st.container(border=True):
        _accent(ACCENT)
        st.caption("Categories — toggle Divers when items in this order are mixed")
        order_vals: dict[str, str] = {}
        for cat in CATEGORY_LABELS:
            c_name, c_tog, c_sel = st.columns([2, 2, 6], vertical_alignment="center")
            c_name.markdown(f"**{cat.title()}**")
            div = c_tog.toggle(
                "Divers", key=f"ord_div_{cat}",
                label_visibility="collapsed",
                help=f"Toggle if {cat} varies across items in this order",
            )
            if div:
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
        oid     = next_order_id(st.session_state.orders_df)
        today_s = date.today().isoformat()
        new_items: list[dict] = []
        cur_sku = next_sku(st.session_state.items_df)
        sku_list: list[str] = []

        for _ in range(int(ord_qty)):
            new_items.append({
                "sku": cur_sku, "status": "In Shipping",
                "brand": order_vals["brand"], "type":  order_vals["type"],
                "style": order_vals["style"], "grade": "",
                "origin": order_vals["origin"], "supplier": order_vals["supplier"],
                "purchase_price": ppi, "sale_price": 0.0, "push_cost": 0.0,
                "markup": float("nan"), "profit": float("nan"), "roi": float("nan"),
                "listed_on": "", "sold_on": "", "cancelled_on": "",
                "order_id": oid,
            })
            sku_list.append(str(cur_sku))
            cur_sku += 1

        st.session_state.orders_df = coerce_orders(pd.concat(
            [st.session_state.orders_df,
             pd.DataFrame([{
                 "order_id": oid, "item_skus": "|".join(sku_list),
                 "quantity": int(ord_qty),
                 **{k: order_vals[k] for k in CATEGORY_LABELS},
                 "total_purchase": ord_total, "price_per_item": ppi,
                 "note": ord_note, "created_on": today_s,
             }])],
            ignore_index=True,
        ))
        save_data(st.session_state.orders_df, ORDERS_PATH)

        st.session_state.items_df = coerce_items(pd.concat(
            [st.session_state.items_df, pd.DataFrame(new_items)], ignore_index=True,
        ))
        save_data(st.session_state.items_df, ITEMS_PATH)
        st.success(
            f":material/check_circle: Order #{oid} created — "
            f"{int(ord_qty)} items (SKU {sku_list[0]}–{sku_list[-1]})."
        )
        st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# TAB 4 — FINANCE
# ═════════════════════════════════════════════════════════════════════════════
with tab_fin:
    # Period selector
    preset = st.pills(
        "Period",
        ["Last Month", "This Month", "This Year", "All Time", "Custom"],
        default="This Year", key="fin_preset",
    )
    preset = preset or "This Year"

    if preset == "Last Month":
        date_from, date_to = _lm_start, _lm_end
    elif preset == "This Month":
        date_from, date_to = _first_this, _today
    elif preset == "This Year":
        date_from, date_to = date(_today.year, 1, 1), _today
    elif preset == "All Time":
        date_from, date_to = date(2020, 1, 1), _today
    else:
        dc1, dc2 = st.columns(2)
        date_from = dc1.date_input("From", value=date(_today.year, 1, 1), key="fin_d_from")
        date_to   = dc2.date_input("To",   value=_today,                  key="fin_d_to")

    d_from, d_to = pd.Timestamp(date_from), pd.Timestamp(date_to)

    # Prepare data
    items_f = coerce_items(st.session_state.items_df.copy())
    items_f["_listed"] = pd.to_datetime(items_f["listed_on"], errors="coerce")
    items_f["_sold"]   = pd.to_datetime(items_f["sold_on"],   errors="coerce")

    in_range   = items_f[items_f["_listed"].between(d_from, d_to) | items_f["_sold"].between(d_from, d_to)]
    sold_items = items_f[items_f["status"].isin(["Sold", "Cancelled"]) & items_f["_sold"].between(d_from, d_to)]

    overhead = coerce_overhead(st.session_state.overhead_df.copy())
    overhead["_date"] = pd.to_datetime(overhead["date"], errors="coerce")
    oh_range = overhead[overhead["_date"].between(d_from, d_to)]

    # KPI calculations
    incidental    = oh_range["amount"].sum()
    item_spend    = in_range["purchase_price"].sum()
    push_spend    = in_range["push_cost"].sum()
    expenses      = item_spend + push_spend
    total_expenses= expenses + incidental
    revenue       = sold_items["sale_price"].sum()
    sold_pp_sum   = sold_items["purchase_price"].sum()
    real_profit   = revenue - sold_pp_sum
    net_profit    = revenue - total_expenses
    total_roi     = (net_profit / total_expenses * 100) if total_expenses > 0 else float("nan")
    real_roi      = (real_profit / sold_pp_sum * 100)   if sold_pp_sum > 0    else float("nan")
    stock_value   = items_f[~items_f["status"].isin(["Sold", "Cancelled"])]["purchase_price"].sum()
    sc            = len(sold_items)
    avg_rev       = revenue / sc        if sc else float("nan")
    avg_prof      = real_profit / sc    if sc else float("nan")
    sold_der      = compute_derived(sold_items) if not sold_items.empty else sold_items
    avg_roi_val   = sold_der["roi"].mean()                 if not sold_der.empty  else float("nan")
    avg_pp_val    = in_range["purchase_price"].mean()      if not in_range.empty  else float("nan")
    avg_sp_val    = sold_items["sale_price"].mean()        if not sold_items.empty else float("nan")
    days_in_range = max((date_to - date_from).days + 1, 1)
    avg_sales_day = sc / days_in_range

    # Previous period
    prev_to_d   = date_from - timedelta(days=1)
    prev_from_d = prev_to_d - timedelta(days=days_in_range - 1)
    p_from, p_to = pd.Timestamp(prev_from_d), pd.Timestamp(prev_to_d)
    prev_sold   = items_f[items_f["status"].isin(["Sold", "Cancelled"]) & items_f["_sold"].between(p_from, p_to)]
    prev_rev    = prev_sold["sale_price"].sum()
    prev_rp     = prev_rev - prev_sold["purchase_price"].sum()
    prev_sc     = len(prev_sold)
    prev_in     = items_f[items_f["_listed"].between(p_from, p_to) | items_f["_sold"].between(p_from, p_to)]
    prev_exp    = prev_in["purchase_price"].sum() + prev_in["push_cost"].sum()
    prev_oh_sum = overhead[overhead["_date"].between(p_from, p_to)]["amount"].sum()
    prev_total_exp = prev_exp + prev_oh_sum

    # ── KPI sections (colour-accented bordered containers) ────────────────
    with st.container(border=True):
        _accent(GREEN)
        st.caption("Revenue & Profit")
        k1 = st.columns(4)
        k1[0].metric("Revenue",     _fm(revenue),     _dm(revenue,     prev_rev))
        k1[1].metric("Real Profit", _fm(real_profit), _dm(real_profit, prev_rp))
        k1[2].metric("Net Profit",  _fm(net_profit))
        k1[3].metric("Sales",       sc, f"{sc - prev_sc:+d}")

    with st.container(border=True):
        _accent(RED)
        st.caption("Expenses")
        k2 = st.columns(4)
        k2[0].metric("Total Expenses",  _fm(total_expenses))
        k2[1].metric("Item + Push Spend",_fm(expenses))
        k2[2].metric("Incidental Costs", _fm(incidental))
        k2[3].metric("Stock Value",      _fm(stock_value))

    with st.container(border=True):
        _accent(PURPLE)
        st.caption("Returns")
        k3 = st.columns(4)
        k3[0].metric("Total ROI",     _fp(total_roi))
        k3[1].metric("Real ROI",      _fp(real_roi))
        k3[2].metric("Avg ROI / Sale",_fp(avg_roi_val))
        k3[3].metric("Avg Sales / Day", f"{avg_sales_day:.2f}")

    with st.container(border=True):
        _accent(ACCENT)
        st.caption("Averages")
        k4 = st.columns(4)
        k4[0].metric("Avg Revenue / Sale",  _fm(avg_rev))
        k4[1].metric("Avg Profit / Sale",   _fm(avg_prof))
        k4[2].metric("Avg Purchase Price",  _fm(avg_pp_val))
        k4[3].metric("Avg Sale Price",      _fm(avg_sp_val))

    # Last-month snapshot (expander)
    lm_sold = items_f[
        items_f["status"].isin(["Sold", "Cancelled"])
        & items_f["_sold"].between(pd.Timestamp(_lm_start), pd.Timestamp(_lm_end))
    ]
    lm_oh  = overhead[overhead["_date"].between(pd.Timestamp(_lm_start), pd.Timestamp(_lm_end))]
    lm_rev = lm_sold["sale_price"].sum()
    lm_rp  = lm_rev - lm_sold["purchase_price"].sum()
    lm_in  = items_f[
        items_f["_listed"].between(pd.Timestamp(_lm_start), pd.Timestamp(_lm_end))
        | items_f["_sold"].between(pd.Timestamp(_lm_start), pd.Timestamp(_lm_end))
    ]
    lm_exp = lm_in["purchase_price"].sum() + lm_in["push_cost"].sum() + lm_oh["amount"].sum()

    with st.expander(f":material/calendar_month: Last month snapshot — {_lm_start:%b %Y}"):
        lmc = st.columns(4)
        lmc[0].metric("Revenue",  _fm(lm_rev))
        lmc[1].metric("Expenses", _fm(lm_exp))
        lmc[2].metric("Profit",   _fm(lm_rp))
        lmc[3].metric("Sales",    len(lm_sold))

    # ── Chart sub-tabs ────────────────────────────────────────────────────
    chart_ts, chart_bd, chart_cmp = st.tabs(
        [":material/show_chart: Time Series",
         ":material/bar_chart: Breakdowns",
         ":material/compare_arrows: Comparisons"],
        on_change="rerun", key="fin_chart_tabs",
    )

    with chart_ts:
        if sold_items.empty and in_range.empty:
            st.info("No data in the selected date range yet. Expand the period or add items.")
        else:
            _sd  = sold_items.dropna(subset=["_sold"]) if not sold_items.empty else pd.DataFrame()
            ch1, ch2 = st.columns(2)
            if sold_items.empty and not in_range.empty:
                ch1.info("No sales yet in this period — stock value chart shown on the right.")

            if not _sd.empty:
                # 1. Revenue vs Expenses (cumulative)
                rev_cum = _sd.groupby("_sold")["sale_price"].sum().sort_index().cumsum()
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
                ch1.plotly_chart(_style_fig(fig_re, money_y=True, date_x=True), width="stretch")

                # 2. Profit cumulative (real + net)
                _sd2 = _sd.copy()
                _sd2["_rp"] = _sd2["sale_price"] - _sd2["purchase_price"]
                _sd2["_np"] = _sd2["sale_price"] - _sd2["purchase_price"] - _sd2["push_cost"]
                rp_cum = _sd2.groupby("_sold")["_rp"].sum().sort_index().cumsum()
                np_cum = _sd2.groupby("_sold")["_np"].sum().sort_index().cumsum()
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
                ch2.plotly_chart(_style_fig(fig_p, money_y=True, date_x=True, zero_line=True), width="stretch")

                # 3. ROI rolling 7-day
                roi_d = compute_derived(_sd).dropna(subset=["roi"])
                if not roi_d.empty:
                    roi_s = (roi_d.groupby("_sold")["roi"].mean().sort_index()
                             .rolling(7, min_periods=1).mean().reset_index())
                    roi_s.columns = ["Date", "ROI"]
                    fig_r = go.Figure()
                    fig_r.add_scatter(
                        x=roi_s["Date"], y=roi_s["ROI"], name="ROI",
                        mode="lines", line=dict(color=PURPLE, width=2.5),
                        fill="tozeroy", fillcolor="rgba(168,85,247,0.08)",
                        hovertemplate="%{y:.1f}%<extra>7-Day Avg ROI</extra>",
                    )
                    fig_r.update_layout(title="ROI (7-Day Rolling Avg)")
                    ch1.plotly_chart(_style_fig(fig_r, pct_y=True, date_x=True, zero_line=True), width="stretch")

                # 4. Daily sales bar
                sc_d = _sd.groupby(_sd["_sold"].dt.date).size().reset_index(name="Count")
                sc_d.columns = ["Date", "Count"]
                fig_sc_bar = go.Figure()
                fig_sc_bar.add_bar(
                    x=sc_d["Date"], y=sc_d["Count"], marker_color=ACCENT,
                    hovertemplate="%{x|%b %d}: %{y} sales<extra></extra>",
                )
                fig_sc_bar.update_layout(title="Daily Sales Count")
                ch2.plotly_chart(_style_fig(fig_sc_bar, date_x=True), width="stretch")

                # 5. Avg prices rolling
                asp = (_sd.groupby("_sold")["sale_price"].mean().sort_index()
                       .rolling(7, min_periods=1).mean())
                fig_ap = go.Figure()
                fig_ap.add_scatter(
                    x=asp.index, y=asp.values, name="Avg Sale Price",
                    mode="lines", line=dict(color=GREEN, width=2.5),
                    hovertemplate="€%{y:,.2f}<extra>Avg Sale Price</extra>",
                )
                app_items = (in_range.dropna(subset=["_listed"])
                             .groupby("_listed")["purchase_price"].mean().sort_index()
                             .rolling(7, min_periods=1).mean())
                if not app_items.empty:
                    fig_ap.add_scatter(
                        x=app_items.index, y=app_items.values, name="Avg Purchase Price",
                        mode="lines", line=dict(color=ORANGE, width=2.5),
                        hovertemplate="€%{y:,.2f}<extra>Avg Purchase Price</extra>",
                    )
                fig_ap.update_layout(title="Avg Prices (7-Day Rolling)")
                ch1.plotly_chart(_style_fig(fig_ap, money_y=True, date_x=True), width="stretch")

            # 6. Stock value area
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
                target = ch2 if not _sd.empty else ch1
                target.plotly_chart(_style_fig(fig_sv, money_y=True, date_x=True), width="stretch")

    with chart_bd:
        # Waterfall: expense composition
        if total_expenses > 0:
            _wf_vals = [item_spend, push_spend, incidental, total_expenses]
            _wf_pcts = [
                f"€{v:,.0f}  ({v/total_expenses*100:.0f}%)" if total_expenses > 0 else f"€{v:,.0f}"
                for v in _wf_vals
            ]
            fig_wf = go.Figure(go.Waterfall(
                orientation="v",
                measure=["relative", "relative", "relative", "total"],
                x=["Item Spend", "Push Costs", "Incidental", "Total"],
                y=[item_spend, push_spend, incidental, 0],
                text=_wf_pcts,
                textposition="outside",
                connector=dict(line=dict(color="rgba(99,122,182,0.25)", width=1, dash="dot")),
                increasing=dict(marker_color=RED),
                decreasing=dict(marker_color=GREEN),
                totals=dict(marker_color=ACCENT),
                hovertemplate="<b>%{x}</b><br>€%{y:,.2f}<extra></extra>",
            ))
            fig_wf.update_layout(title="Expense Composition (Waterfall)",
                                 uniformtext_minsize=9)
            st.plotly_chart(_style_fig(fig_wf, money_y=True, height=300), width="stretch")
        else:
            st.info("No expenses in the selected period.")

        bd1, bd2 = st.columns(2)
        if not sold_items.empty:
            for col_obj, dim, title in [
                (bd1, "brand", "Revenue by Brand (Top 12)"),
                (bd2, "type",  "Revenue by Type"),
            ]:
                ex = explode_pipe_col(sold_items, dim)
                ex = ex[ex[dim].astype(str).ne("") & ex[dim].astype(str).ne("nan")]
                if not ex.empty:
                    grp = ex.groupby(dim).agg(
                        Revenue=("sale_price", "sum"),
                        Profit=("profit", "sum"),
                    ).sort_values("Revenue", ascending=True).tail(12)
                    bar_colors = [GREEN if (pd.notna(p) and p >= 0) else RED for p in grp["Profit"]]
                    fig_bar = go.Figure()
                    fig_bar.add_bar(
                        y=grp.index, x=grp["Revenue"], name="Revenue",
                        orientation="h", marker_color=ACCENT,
                        hovertemplate="%{y}: €%{x:,.2f}<extra>Revenue</extra>",
                    )
                    fig_bar.add_bar(
                        y=grp.index, x=grp["Profit"], name="Profit",
                        orientation="h", marker_color=bar_colors, opacity=0.85,
                        hovertemplate="%{y}: €%{x:,.2f}<extra>Profit</extra>",
                    )
                    fig_bar.update_layout(title=title, barmode="overlay")
                    col_obj.plotly_chart(
                        _style_fig(fig_bar, height=340, hovermode="closest"), width="stretch"
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
                    x=roi_vals, marker_color=PURPLE, opacity=0.8, nbinsx=20,
                    hovertemplate="ROI ~%{x:.0f}%: %{y} items<extra></extra>",
                )
                fig_hist.add_vline(x=0, line_dash="dot", line_color=RED, line_width=1.5,
                                   annotation_text="Break-even", annotation_position="top right")
                fig_hist.add_vline(x=mean_roi, line_dash="dash", line_color=GREEN, line_width=1.5,
                                   annotation_text=f"Avg {mean_roi:.1f}%",
                                   annotation_position="top left")
                fig_hist.update_layout(title="ROI Distribution (Sold Items)",
                                       xaxis_title="ROI %", yaxis_title="Items")
                st.plotly_chart(_style_fig(fig_hist, height=280), width="stretch")

    with chart_cmp:
        cmp1, cmp2 = st.columns(2)

        # Current vs previous period
        if max(revenue, expenses, abs(real_profit), prev_rev, prev_exp, abs(prev_rp)) == 0:
            cmp1.info("No financial data in the selected period or its comparison window.")
        else:
            fig_cmp = go.Figure()
            metric_labels = ["Revenue", "Item+Push Spend", "Real Profit"]
            curr_vals = [revenue, expenses, real_profit]
            prev_vals = [prev_rev, prev_exp, prev_rp]
            fig_cmp.add_bar(
                name=f"Current  ({date_from:%b %d}–{date_to:%b %d})",
                x=metric_labels, y=curr_vals,
                marker_color=[GREEN, ORANGE, TEAL],
                hovertemplate="%{x}: €%{y:,.2f}<extra>Current</extra>",
            )
            fig_cmp.add_bar(
                name=f"Previous ({prev_from_d:%b %d}–{prev_to_d:%b %d})",
                x=metric_labels, y=prev_vals,
                marker_color=["rgba(34,197,94,0.45)", "rgba(249,115,22,0.45)", "rgba(20,184,166,0.45)"],
                hovertemplate="%{x}: €%{y:,.2f}<extra>Previous</extra>",
            )
            fig_cmp.update_layout(title="Current vs Previous Period", barmode="group",
                                   bargroupgap=0.12)
            cmp1.plotly_chart(_style_fig(fig_cmp, money_y=True, zero_line=True), width="stretch")

        # Monthly trend (last 6 months — all-time data, not period-filtered)
        items_all = coerce_items(st.session_state.items_df.copy())
        items_all["_sold_dt"] = pd.to_datetime(items_all["sold_on"], errors="coerce")
        hist_sold = items_all[
            items_all["status"].isin(["Sold", "Cancelled"]) & items_all["_sold_dt"].notna()
        ].copy()

        if not hist_sold.empty:
            hist_sold = compute_derived(hist_sold)
            hist_sold["_month"] = hist_sold["_sold_dt"].dt.to_period("M")
            monthly = (
                hist_sold.groupby("_month")
                .agg(Revenue=("sale_price", "sum"), Profit=("profit", "sum"))
                .tail(6)
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
            fig_mon.update_layout(title="Monthly Revenue & Profit (Last 6 Months)", barmode="group")
            cmp2.plotly_chart(_style_fig(fig_mon, money_y=True, zero_line=True), width="stretch")
        else:
            cmp2.info("No historical sales data for monthly trend.")

    # Overhead (editable data_editor)
    with st.expander(":material/receipt_long: Incidental Costs (Overhead)"):
        oh_c1, oh_c2, oh_c3, oh_c4 = st.columns([2, 3, 2, 1], vertical_alignment="bottom")
        oh_amt  = oh_c1.number_input("Amount €",    min_value=0.0, format="%.2f", key="oh_amt")
        oh_desc = oh_c2.text_input("Description",  key="oh_desc")
        oh_dt   = oh_c3.date_input("Date",          value=_today,  key="oh_dt")
        if oh_c4.button(":material/add:", key="oh_add", width="stretch") and oh_amt > 0:
            st.session_state.overhead_df = pd.concat(
                [st.session_state.overhead_df,
                 pd.DataFrame([{"date": oh_dt.isoformat(), "amount": oh_amt,
                                "description": oh_desc}])],
                ignore_index=True,
            )
            save_data(st.session_state.overhead_df, OVERHEAD_PATH)
            st.rerun()

        if not st.session_state.overhead_df.empty:
            oh_display = (
                coerce_overhead(st.session_state.overhead_df)
                .sort_values("date", ascending=False)
                .reset_index(drop=True)
            )
            # DateColumn requires datetime-like dtype; CSV loads dates as strings.
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

            def _oh_norm(df: pd.DataFrame) -> pd.DataFrame:
                d = df.copy()
                d["date"]        = d["date"].apply(_to_iso)
                d["amount"]      = pd.to_numeric(d["amount"], errors="coerce").fillna(0.0).round(4)
                d["description"] = d["description"].fillna("").astype(str)
                return d.reset_index(drop=True).astype(str)

            if (
                edited_oh.shape != oh_display.shape
                or not _oh_norm(edited_oh).equals(_oh_norm(oh_display))
            ):
                save_oh = edited_oh.copy()
                save_oh["date"]        = save_oh["date"].apply(_to_iso)
                save_oh["amount"]      = pd.to_numeric(save_oh["amount"],    errors="coerce").fillna(0.0)
                save_oh["description"] = save_oh["description"].fillna("").astype(str)
                st.session_state.overhead_df = save_oh
                save_data(save_oh, OVERHEAD_PATH)
                st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
# TAB 5 — INSIGHTS
# ═════════════════════════════════════════════════════════════════════════════
with tab_ins:
    _all   = coerce_items(st.session_state.items_df.copy())
    closed = _all[_all["status"].isin(["Sold", "Cancelled"])].copy()

    if closed.empty:
        with st.container(border=True):
            st.markdown("### No sales data yet")
            st.caption(
                "Insights unlock once you have sold or cancelled items. "
                "Add items and mark them as Sold to start seeing analytics."
            )
    else:
        closed = compute_derived(closed)
        closed["_sold"] = pd.to_datetime(closed["sold_on"], errors="coerce")
        lm_mask   = closed["_sold"].between(pd.Timestamp(_lm_start), pd.Timestamp(_lm_end))
        closed_lm = closed[lm_mask]

        ins_period = st.pills(
            "Period", ["All Time", "Last Month"],
            default="All Time", key="ins_period",
        )
        ins_period = ins_period or "All Time"
        ins_data   = closed if ins_period == "All Time" else closed_lm

        dims = ["brand", "type", "style", "grade", "origin", "supplier"]

        # ── Performance by dimension (6 bar charts in 2×3 grid) ──────────
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
                ).sort_values("Revenue", ascending=True).tail(10)
                bar_colors = [GREEN if (pd.notna(p) and p >= 0) else RED for p in grp["Profit"]]
                fig_dim = go.Figure()
                fig_dim.add_bar(
                    y=grp.index, x=grp["Revenue"], name="Revenue",
                    orientation="h", marker_color=ACCENT,
                    hovertemplate="%{y}: €%{x:,.2f}<extra>Revenue</extra>",
                )
                fig_dim.add_bar(
                    y=grp.index, x=grp["Profit"], name="Profit",
                    orientation="h", marker_color=bar_colors, opacity=0.85,
                    hovertemplate="%{y}: €%{x:,.2f}<extra>Profit</extra>",
                )
                fig_dim.update_layout(
                    title=f"By {dim.title()} — {ins_period}",
                    barmode="overlay", yaxis_title="",
                )
                col_obj.plotly_chart(
                    _style_fig(fig_dim, height=280, hovermode="closest"), width="stretch"
                )

        # ── Deep insight charts ───────────────────────────────────────────
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
                x=dts_clean, marker_color=TEAL, opacity=0.85, nbinsx=20,
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
            di1.plotly_chart(_style_fig(fig_dts, height=280), width="stretch")
        else:
            di1.info("Need sold items with both listed and sold dates for this chart.")

        # Purchase vs Sale price scatter
        sc_data = closed[(closed["purchase_price"] > 0) & (closed["sale_price"] > 0)].copy()
        if not sc_data.empty:
            max_val   = max(sc_data["purchase_price"].max(), sc_data["sale_price"].max()) * 1.1
            has_grade = sc_data["grade"].astype(str).ne("").any()
            fig_sc2 = px.scatter(
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
            # Break-even diagonal
            fig_sc2.add_scatter(
                x=[0, max_val], y=[0, max_val],
                mode="lines",
                line=dict(color="rgba(255,255,255,0.22)", dash="dot", width=1),
                name="Break-even", showlegend=True, hoverinfo="skip",
            )
            di2.plotly_chart(
                _style_fig(fig_sc2, height=280, money_y=True, hovermode="closest"),
                width="stretch",
            )
        else:
            di2.info("Need items with both purchase and sale price for the scatter plot.")

        # Top 10 most profitable items
        st.markdown("#### :material/format_list_numbered: Top 10 Most Profitable Items")
        top10 = closed.dropna(subset=["profit"]).sort_values("profit", ascending=False).head(10)
        if not top10.empty:
            t10_cols = ["sku", "brand", "type", "style", "grade",
                        "purchase_price", "sale_price", "markup", "profit", "roi"]
            st.dataframe(
                top10[[c for c in t10_cols if c in top10.columns]].reset_index(drop=True),
                width="stretch", hide_index=True,
                column_config={
                    "purchase_price": st.column_config.NumberColumn("Purchase €", format="€%.2f"),
                    "sale_price":     st.column_config.NumberColumn("Sale €",     format="€%.2f"),
                    "markup":         st.column_config.NumberColumn("Markup €",   format="€%.2f"),
                    "profit":         st.column_config.NumberColumn("Profit €",   format="€%.2f"),
                    "roi":            st.column_config.NumberColumn("ROI",        format="%.1f%%"),
                },
            )

        # ── Ideal Item ────────────────────────────────────────────────────
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
                _accent(AMBER)
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
                    column_config={
                        "purchase_price": st.column_config.NumberColumn("Purchase €", format="€%.2f"),
                        "sale_price":     st.column_config.NumberColumn("Sale €",     format="€%.2f"),
                        "markup":         st.column_config.NumberColumn("Markup €",   format="€%.2f"),
                        "profit":         st.column_config.NumberColumn("Profit €",   format="€%.2f"),
                        "roi":            st.column_config.NumberColumn("ROI",        format="%.1f%%"),
                    },
                )
            else:
                st.warning("No single item matches all top categories simultaneously.")
                for dim, val in ideal_profile.items():
                    dm = closed[closed[dim].astype(str).str.contains(val, regex=False, na=False)]
                    if not dm.empty:
                        best = dm.sort_values("sale_price", ascending=False).iloc[0]
                        st.caption(
                            f"**{dim.title()} = {val}:** "
                            f"{_fm(best['sale_price'])} revenue — SKU {int(best['sku'])}"
                        )
        else:
            st.info("Not enough data to determine an ideal item profile.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 6 — LOOKUP VALUES
# ═════════════════════════════════════════════════════════════════════════════
with tab_cfg:
    st.markdown("### :material/tune: Lookup Values")
    st.caption(
        "Manage the dropdown options available when adding items and orders. "
        "Changes take effect immediately."
    )

    cfg_df = st.session_state.config_df

    # ── Add new value ─────────────────────────────────────────────────────
    with st.container(border=True):
        _accent(TEAL)
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
                # prevent duplicates within the same category
                existing = get_config_options(cfg_df, add_cat)
                if add_val.strip() in existing:
                    st.warning(f"**{add_val.strip()}** already exists in {add_cat}.")
                else:
                    st.session_state.config_df = pd.concat(
                        [cfg_df, pd.DataFrame([{"category": add_cat, "value": add_val.strip()}])],
                        ignore_index=True,
                    )
                    save_data(st.session_state.config_df, CONFIG_PATH)
                    st.rerun()
            else:
                st.warning("Enter a value before clicking Add.")

    st.markdown("")  # spacer

    # ── Current values — one card per category ────────────────────────────
    cat_cols = st.columns(len(CATEGORY_LABELS), gap="small")
    for col_obj, cat in zip(cat_cols, CATEGORY_LABELS):
        with col_obj:
            with st.container(border=True):
                _accent(ACCENT)
                st.caption(cat.title())
                cfg_df = st.session_state.config_df  # re-read after any delete
                cat_vals = get_config_options(cfg_df, cat)
                if not cat_vals:
                    st.markdown("*No values yet*")
                else:
                    for val in cat_vals:
                        # find the row index so we can delete it
                        mask = (cfg_df["category"] == cat) & (cfg_df["value"] == val)
                        row_idx = cfg_df[mask].index
                        v1, v2 = st.columns([5, 1], vertical_alignment="center")
                        v1.markdown(f"`{val}`")
                        if row_idx.size > 0:
                            if v2.button(
                                ":material/close:", key=f"del_{cat}_{val}",
                                width="stretch",
                            ):
                                st.session_state.config_df = (
                                    cfg_df.drop(row_idx).reset_index(drop=True)
                                )
                                save_data(st.session_state.config_df, CONFIG_PATH)
                                st.rerun()
