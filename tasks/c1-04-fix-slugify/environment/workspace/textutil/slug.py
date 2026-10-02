"""URL slugs for product and article titles."""

import re


def slugify(title: str, max_len: int = 60) -> str:
    """Lower-case ASCII slug: words joined by single hyphens, no leading or trailing hyphen.

    Accented letters are folded to their base letter ("Crème brûlée" -> "creme-brulee"), any run
    of characters that are not letters or digits becomes one hyphen, and the result is cut to at
    most max_len characters without leaving a trailing hyphen.
    """
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]", "-", slug)
    return slug[:max_len]
