"""KEYDATA -> financials column mapping, per PRD §3.1.

Confirmed by name against the live Supabase schema; REPORTSEQ is
intentionally NOT part of this mapping (it means different KEYDATA
depending on which era of the CSV a row comes from -- see PRD §2).
"""

KEYDATA_TO_COLUMN: dict[str, str] = {
    "Sales": "revenue",
    "OperationIncome": "operating_profit",
    "NetIncome": "net_income",
    "OperationIncomeRate": "operating_margin",
    "NetIncomeRate": "net_margin",
    "ROE": "roe",
    "DebtRatio": "debt_ratio",
    "CurrentRatio": "quick_ratio",  # PRD §5.2: naming mismatch, mapped as-is intentionally
    "ReserveRatio": "reserve_ratio",
    "EPS": "eps",
    "PER": "per",
    "BPS": "bps",
    "PBR": "pbr",
    "Dividends": "dps",
    "MARKETDIVRATE": "dividend_yield",
    "DIVPAYOUTRATIO": "payout_ratio",
}

NUMERIC_COLUMNS: tuple[str, ...] = tuple(KEYDATA_TO_COLUMN.values())
