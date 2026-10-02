"""Calendar helpers for monthly and quarterly closes."""

from datetime import date, timedelta


def month_end(day: date) -> date:
    """Last day of the month containing day."""
    first_next = date(day.year, day.month + 1, 1)
    return first_next - timedelta(days=1)


def quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1
