"""Data loading, saving, computation, and automation for the Vinted Tracker."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# localStorage storage keys — single source of truth shared by all views
# ---------------------------------------------------------------------------

ITEMS_KEY    = "items"
ORDERS_KEY   = "orders"
OVERHEAD_KEY = "overhead"
CONFIG_KEY   = "config"

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

CATEGORY_LABELS = ["brand", "type", "style", "origin", "supplier"]

# ---------------------------------------------------------------------------
# Sentinel / sort constants
# ---------------------------------------------------------------------------

# Sentinel value stored in order_id when an item has no associated order.
NO_ORDER_SENTINEL: int = -1

# Priority assigned to statuses not found in STATUS_SORT (sorts them last).
UNKNOWN_STATUS_PRIORITY: int = 5

# Temporary sort value that pushes "no order" items to the end of the list.
SORT_SENTINEL: int = 999_999

# ---------------------------------------------------------------------------
# Date serialization helpers
# ---------------------------------------------------------------------------


def _to_iso(val: object) -> str:
    """Convert *val* to an ISO date string, or return '' if not convertible."""
    try:
        if val is None or pd.isna(val):  # type: ignore[arg-type]
            return ""
    except (ValueError, TypeError):
        pass
    if hasattr(val, "isoformat"):
        return val.isoformat()[:10]  # type: ignore[union-attr]
    s = str(val).strip()
    return "" if s in ("", "NaT", "nan", "None") else s


def norm_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize all DATE_COLS_ITEMS columns to ISO strings (or empty string)."""
    df = df.copy()
    for c in DATE_COLS_ITEMS:
        if c in df.columns:
            df[c] = df[c].apply(_to_iso)
    return df


# ---------------------------------------------------------------------------
# Load / Save (serialization helpers — callers own the actual storage I/O)
# ---------------------------------------------------------------------------


def df_to_storage(df: pd.DataFrame) -> list[dict[str, Any]]:
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


def has_changed(
    before: pd.DataFrame,
    after: pd.DataFrame,
    sort_col: str | None = None,
) -> bool:
    """Return True if *after* differs from *before*.

    Uses ``DataFrame.equals()`` which treats NaN == NaN as True, preventing
    false positives when markup/profit/roi are NaN for unsold items.
    Using ``df_to_storage()`` for this comparison is incorrect: each
    ``.to_dict("records")`` call creates new numpy scalar NaN objects that
    never compare equal via ``==``, causing spurious "changed" detections.
    """
    if before.shape != after.shape:
        return True
    if sort_col:
        before = before.sort_values(sort_col).reset_index(drop=True)
        after = after.sort_values(sort_col).reset_index(drop=True)
    return not before.equals(after)


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
    df["order_id"] = (
        pd.to_numeric(df["order_id"], errors="coerce")
        .fillna(NO_ORDER_SENTINEL)
        .astype(int)
    )
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
# Safe coercion helpers
# ---------------------------------------------------------------------------


def _safe_float(val: object, default: float = 0.0) -> float:
    """Convert *val* to float, returning *default* on any conversion failure."""
    try:
        return float(val) if val is not None else default  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Auto-increment helpers
# ---------------------------------------------------------------------------


def _next_id(df: pd.DataFrame, col: str) -> int:
    """Return the next available integer ID for *col* in *df*."""
    if df.empty:
        return 1
    vals = pd.to_numeric(df[col], errors="coerce").dropna()
    return int(vals.max()) + 1 if len(vals) > 0 else 1


def next_sku(items_df: pd.DataFrame) -> int:
    return _next_id(items_df, "sku")


def next_order_id(orders_df: pd.DataFrame) -> int:
    return _next_id(orders_df, "order_id")


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

    def _tracker(row: pd.Series) -> str:
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


def apply_automation(row: dict[str, Any]) -> dict[str, Any]:
    """Enforce status-date-profit rules on a single item row dict."""
    today_str = date.today().isoformat()
    sp = _safe_float(row.get("sale_price"))
    pp = _safe_float(row.get("purchase_price"))
    pc = _safe_float(row.get("push_cost"))
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
    out["_status_priority"] = out["status"].map(STATUS_SORT).fillna(UNKNOWN_STATUS_PRIORITY)
    out["_order_id_sort"] = out["order_id"].replace(NO_ORDER_SENTINEL, SORT_SENTINEL)
    out = out.sort_values(["_status_priority", "_order_id_sort", "sku"]).drop(
        columns=["_status_priority", "_order_id_sort"]
    )
    return out.reset_index(drop=True)
