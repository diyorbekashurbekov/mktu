"""Display formatting. Values are rounded to 2 decimals only here (on screen)."""
from __future__ import annotations

NA = "н/д"


def _group(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return " ".join(out)


def num(x, digits: int = 2) -> str:
    if x is None:
        return NA
    neg = x < 0
    s = f"{abs(x):.{digits}f}"
    if digits:
        ip, fp = s.split(".")
        s = _group(ip) + "," + fp
    else:
        s = _group(s)
    return ("−" if neg else "") + s


def money(x, digits: int = 2) -> str:
    return NA if x is None else num(x, digits) + " ₸"


def money0(x) -> str:
    return money(x, 0)


def pct(x, digits: int = 2) -> str:
    return NA if x is None else num(x, digits) + "%"


def pp(x, digits: int = 2) -> str:
    if x is None:
        return NA
    return ("+" if x >= 0 else "") + num(x, digits) + " п.п."


def signed_money(x) -> str:
    if x is None:
        return NA
    return ("+" if x >= 0 else "") + money(x, 0)


def rows_ref(sheet: str, rows) -> str:
    """[2, 3, 4, 7] -> 'Sheet!2–4, 7'"""
    rows = sorted(set(r for r in rows if r))
    if not rows:
        return sheet
    parts, start, prev = [], rows[0], rows[0]
    for r in rows[1:] + [None]:
        if r is not None and r == prev + 1:
            prev = r
            continue
        parts.append(f"{start}" if start == prev else f"{start}–{prev}")
        if r is not None:
            start = prev = r
    return f"{sheet}!{', '.join(parts)}"


def short_money(x) -> str:
    if x is None:
        return NA
    a = abs(x)
    if a >= 1e9:
        return num(x / 1e9, 2) + " млрд ₸"
    if a >= 1e6:
        return num(x / 1e6, 1) + " млн ₸"
    return money(x, 0)
