from decimal import Decimal
from typing import Optional, Union

Number = Union[int, float, Decimal]


def humanize_number(value: Optional[Number], decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    if value == 0:
        return "0"
    num = float(value)
    abs_value = abs(num)
    if abs_value >= 1_000_000_000:
        return f"{num / 1_000_000_000:.{decimals}f}B"
    if abs_value >= 1_000_000:
        return f"{num / 1_000_000:.{decimals}f}M"
    if abs_value >= 1_000:
        return f"{num / 1_000:.{decimals}f}K"
    return f"{num:.{decimals}f}"


def format_usd(value: Optional[Number]) -> str:
    if value is None:
        return "N/A"
    num = float(value)
    if abs(num) >= 1:
        return f"${num:,.2f}"
    if abs(num) >= 0.01:
        return f"${num:,.4f}"
    return f"${num:,.6f}"


def format_percent(value: Optional[Number]) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.2f}%"


def format_token_amount(value: Optional[Number]) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):,.2f}"

