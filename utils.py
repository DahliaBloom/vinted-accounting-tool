"""Data loading, saving, computation, and automation for the Vinted Tracker."""

import pandas as pd
import numpy as np
from datetime import date

# ---------------------------------------------------------------------------
# Schemas (column order is the canonical CSV column order)
# ---------------------------------------------------------------------------

ITEMS_SCHEMA = [
    "sku", "status", "brand", "type", "style", "grade", "origin", "supplier",
    "purchase_price", "sale_price", "push_cost", "markup", "profit", "roi",
    "listed_on", "sold_on", "cancelled_on", "order_id",
]

ORDERS_SCHEMA = [
    "order_id", "item_skus", "quantity", "origin", "supplier", "brand",
    "type", "style", "total_purchase", "price_per_item", "note", "created_on",
]

OVERHEAD_SCHEMA = ["date", "amount", "description"]
CONFIG_SCHEMA = ["category", "value"]

STATUS_OPTIONS = ["In Shipping", "Pending", "Listed", "Sold", "Cancelled"]
GRADE_OPTIONS = ["A", "B+", "B", "C"]

DATE_COLS_ITEMS = ["listed_on", "sold_on", "cancelled_on"]

STATUS_SORT = {
    "In Shipping": 0, "Pending": 1, "Listed": 2, "Sold": 3, "Cancelled": 4,
}

STATUS_BADGE = {
    "All Items": ("blue",    ":material/inventory_2:"),
    "In Shipping": ("blue",    ":material/local_shipping:"),
    "Pending":     ("orange",  ":material/deployed_code_history:"),
    "Listed":      ("primary", ":material/sell:"),
    "Sold":        ("green",   ":material/check_circle:"),
    "Cancelled":   ("gray",    ":material/cancel:"),
}

CATEGORY_LABELS = ["brand", "type", "style", "origin", "supplier"]

# ---------------------------------------------------------------------------
# Load / Save (localStorage)
# ---------------------------------------------------------------------------


def df_to_storage(df: pd.DataFrame) -> list[dict]:
    """Serialize a DataFrame to a JSON-safe list of records."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d").fillna("")
    return out.to_dict("records")


def df_from_storage(records: list[dict] | None, schema: list[str]) -> pd.DataFrame:
    """Deserialize records from localStorage into a DataFrame aligned to schema."""
    if not records:
        return pd.DataFrame(columns=schema)
    df = pd.DataFrame(records)
    for col in schema:
        if col not in df.columns:
            df[col] = ""
    return df[schema]


# ---------------------------------------------------------------------------
# Type coercion  (CSV stores everything as strings – coerce after loading)
# ---------------------------------------------------------------------------


def coerce_items(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("purchase_price", "sale_price", "push_cost"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in ("markup", "profit", "roi"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["sku"] = pd.to_numeric(df["sku"], errors="coerce").fillna(0).astype(int)
    df["order_id"] = pd.to_numeric(df["order_id"], errors="coerce").fillna(-1).astype(int)
    return df


def coerce_orders(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("total_purchase", "price_per_item"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["order_id"] = pd.to_numeric(df["order_id"], errors="coerce").fillna(0).astype(int)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    return df


def coerce_overhead(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    return df


# ---------------------------------------------------------------------------
# Auto-increment helpers
# ---------------------------------------------------------------------------


def next_sku(items_df: pd.DataFrame) -> int:
    if items_df.empty:
        return 1
    vals = pd.to_numeric(items_df["sku"], errors="coerce").dropna()
    return int(vals.max()) + 1 if len(vals) > 0 else 1


def next_order_id(orders_df: pd.DataFrame) -> int:
    if orders_df.empty:
        return 1
    vals = pd.to_numeric(orders_df["order_id"], errors="coerce").dropna()
    return int(vals.max()) + 1 if len(vals) > 0 else 1


# ---------------------------------------------------------------------------
# Derived / display columns
# ---------------------------------------------------------------------------


def compute_derived(items_df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with markup, profit, roi, and days_tracker computed.
    *days_tracker* is display-only and must never be persisted."""
    df = items_df.copy()
    pp = pd.to_numeric(df["purchase_price"], errors="coerce").fillna(0.0)
    sp = pd.to_numeric(df["sale_price"], errors="coerce").fillna(0.0)
    pc = pd.to_numeric(df["push_cost"], errors="coerce").fillna(0.0)

    raw_markup = sp - pp
    raw_profit = sp - pp - pc
    df["markup"] = np.where(sp > 0, raw_markup, np.nan)
    df["profit"] = np.where(sp > 0, raw_profit, np.nan)
    df["roi"] = np.where((pp > 0) & (sp > 0), (raw_profit / pp) * 100, np.nan)

    today = pd.Timestamp.today().normalize()

    def _tracker(row):
        raw = row.get("listed_on", "")
        if not raw or str(raw).strip() in ("", "NaT", "nan", "None"):
            return ""
        listed = pd.to_datetime(raw, errors="coerce")
        if pd.isna(listed):
            return ""
        status = str(row.get("status", ""))
        if status == "Listed":
            return f"{(today - listed).days}d listed"
        if status == "Sold":
            sold = pd.to_datetime(row.get("sold_on", ""), errors="coerce")
            return f"Sold after {(sold - listed).days}d" if pd.notna(sold) else ""
        if status == "Cancelled":
            canc = pd.to_datetime(row.get("cancelled_on", ""), errors="coerce")
            return f"Cancelled after {(canc - listed).days}d" if pd.notna(canc) else ""
        return ""

    df["days_tracker"] = df.apply(_tracker, axis=1)
    return df


# ---------------------------------------------------------------------------
# Automation rules (applied on every save / edit)
# ---------------------------------------------------------------------------


def apply_automation(row: dict) -> dict:
    """Enforce status-date-profit rules on a single item row dict."""
    today_str = date.today().isoformat()
    sp = float(row.get("sale_price") or 0)
    pp = float(row.get("purchase_price") or 0)
    pc = float(row.get("push_cost") or 0)
    status = str(row.get("status", ""))

    if sp > 0 and status not in ("Sold", "Cancelled"):
        row["status"] = "Sold"
        status = "Sold"

    if status == "Sold" and not row.get("sold_on"):
        row["sold_on"] = today_str
    if status == "Listed" and not row.get("listed_on"):
        row["listed_on"] = today_str
    if status == "Cancelled" and not row.get("cancelled_on"):
        row["cancelled_on"] = today_str

    if sp > 0:
        row["markup"] = sp - pp
        row["profit"] = sp - pp - pc
        row["roi"] = ((sp - pp - pc) / pp * 100) if pp > 0 else float("nan")
    else:
        row["markup"] = float("nan")
        row["profit"] = float("nan")
        row["roi"] = float("nan")

    return row


# ---------------------------------------------------------------------------
# Config lookup
# ---------------------------------------------------------------------------


def get_config_options(config_df: pd.DataFrame, category: str) -> list[str]:
    """Return a sorted list of lookup values for *category*."""
    if config_df.empty:
        return []
    mask = config_df["category"].astype(str) == category
    return sorted(config_df.loc[mask, "value"].dropna().unique().tolist())


# ---------------------------------------------------------------------------
# Pipe-separated field helpers
# ---------------------------------------------------------------------------


def explode_pipe_col(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Split a pipe-separated column into one row per value."""
    result = df.copy()
    result[col] = result[col].astype(str).str.split("|")
    result = result.explode(col, ignore_index=True)
    result[col] = result[col].str.strip()
    return result[result[col].ne("")]


# ---------------------------------------------------------------------------
# Sorting helpers
# ---------------------------------------------------------------------------


def sort_items_default(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by status priority → order_id → sku (the canonical default)."""
    out = df.copy()
    out["_so"] = out["status"].map(STATUS_SORT).fillna(5)
    out["_oid"] = out["order_id"].replace(-1, 999_999)
    out = out.sort_values(["_so", "_oid", "sku"]).drop(columns=["_so", "_oid"])
    return out.reset_index(drop=True)
