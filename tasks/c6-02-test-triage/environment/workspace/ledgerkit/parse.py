"""Parse amounts as they appear in bank exports."""

import re
from decimal import Decimal, InvalidOperation


def parse_amount(text: str) -> Decimal:
    """Parse "12.50", "$99.00", "1,234.50" or the accounting negative "(12.00)" (= -12.00).

    Raises ValueError for anything else.
    """
    cleaned = re.sub(r"[$\s]", "", text)
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not an amount: {text!r}") from None
