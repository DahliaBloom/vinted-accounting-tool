# Vinted Accounting Tool

A personal Streamlit dashboard for tracking Vinted resale inventory, finances, and analytics. All data is persisted in browser localStorage — no server, no database required.

## Features

- **Warehouse** — full inventory table with inline editing, per-status sub-tabs (In Shipping, Pending, Listed, Sold, Cancelled), and order cards
- **Add Item** — form for adding individual items with auto-incrementing SKU and automatic profit/ROI calculation on save
- **Add Order** — bulk order creation that auto-generates items and links them to a parent order
- **Finance** — period-selectable KPI dashboard (revenue, profit, ROI, expenses), time-series and breakdown charts, overhead (incidental costs) CRUD
- **Insights** — dimension performance charts (brand, type, style, grade, origin, supplier), deep analytics (time-to-sell, scatter), top-10 profitability, ideal item profile
- **Lookup** — manage dropdown options (brands, types, styles, origins, suppliers) used across forms

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Setup

```bash
# Clone and enter the project
git clone <repo-url>
cd vinted-accounting-tool

# Install dependencies
uv sync

# Run the app
uv run streamlit run app.py
```

Or with plain pip:

```bash
pip install -e .
streamlit run app.py
```

## Project Structure

```
app.py              Entry point: page config, storage init, CSS, tab routing (~70 lines)
ui.py               UI helpers: colours, chart styling, formatters, column configs
utils.py            Domain logic: schemas, coercion, automation, sorting, serialization
views/
  warehouse.py      Inventory editor and order display
  add_item.py       Single-item add form
  add_order.py      Bulk order creation form
  finance.py        KPI dashboard and charts
  insights.py       Analytics and ideal item
  lookup.py         Dropdown value management
```

## Data Storage

All data lives in browser localStorage under the key `vinted_storage`. There is no server-side persistence. Data is lost if browser storage is cleared.

## Development

Linting and formatting is configured via [ruff](https://github.com/astral-sh/ruff):

```bash
uv run ruff check .
uv run ruff format .
```
