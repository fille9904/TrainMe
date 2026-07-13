from __future__ import annotations

import html
from typing import Any


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def check_items(items: list[str]) -> str:
    return "".join(f"<li>{esc(item)}</li>" for item in items)
