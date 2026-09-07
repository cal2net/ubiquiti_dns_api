from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _lit(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def eq(field: str, value: Any) -> str:
    return f"{field}.eq({_lit(value)})"


def ne(field: str, value: Any) -> str:
    return f"{field}.ne({_lit(value)})"


def like(field: str, value: str) -> str:
    return f"{field}.like({_lit(value)})"


def in_(field: str, values: Sequence[Any]) -> str:
    return f"{field}.in({','.join(_lit(v) for v in values)})"


def not_in(field: str, values: Sequence[Any]) -> str:
    return f"{field}.notIn({','.join(_lit(v) for v in values)})"


def and_(*expressions: str) -> str:
    if len(expressions) == 1:
        return expressions[0]
    return f"and({','.join(expressions)})"


def or_(*expressions: str) -> str:
    if len(expressions) == 1:
        return expressions[0]
    return f"or({','.join(expressions)})"


def combine(*expressions: str | None) -> str | None:
    parts = [expr for expr in expressions if expr]
    if not parts:
        return None
    return and_(*parts)
