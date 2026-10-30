"""Shared API-equivalent rates and normalized billable usage."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from relay.errors import RelayError

if TYPE_CHECKING:
    from relay.config import Config


@dataclass(frozen=True)
class Rate:
    input: float
    cached_input: float
    output: float
    cache_write_30m: float | None = None
    cache_write_12h: float | None = None


@dataclass(frozen=True)
class Usage:
    thread: str
    model: str
    input: int
    cached_input: int
    output: int
    cache_write_30m: int | None = 0
    cache_write_12h: int | None = 0
    unavailable: str | None = None


class Unpriced(RelayError):
    """Usage cannot be priced from the available billing evidence."""


RATES: dict[str, Rate] = {
    "gpt-6-astra": Rate(10, 1, 50, 12.5, 25),
    "gpt-6.1-sol": Rate(2, 0.1, 10, 2.5, 5),
    "gpt-6.1-terra": Rate(1, 0.05, 5, 1.25, 2.5),
    "gpt-6-luna": Rate(0.1, 0.01, 0.5, 0.125, 0.25),
}
SOURCE = "https://developers.openai.com/api/docs/pricing"


def validate_rate(value: Rate, model: str) -> Rate:
    """Validate both loaded overrides and rates supplied directly by callers."""
    if not isinstance(value, Rate):
        raise Unpriced(f"invalid rate for model {model!r}")
    for name in ("input", "cached_input", "output", "cache_write_30m", "cache_write_12h"):
        number = getattr(value, name)
        if number is None and name.startswith("cache_write_"):
            continue
        try:
            valid = (
                isinstance(number, (int, float))
                and not isinstance(number, bool)
                and number >= 0
                and isfinite(number)
            )
        except OverflowError:
            valid = False
        if not valid:
            raise Unpriced(f"rate {model!r}.{name} must be a finite nonnegative number")
    return value


def rate(cfg: Config, model: str) -> Rate:
    if model in cfg.prices:
        value = cfg.prices[model]
    elif model in RATES:
        value = RATES[model]
    else:
        raise Unpriced(f"unpriced model {model!r}")
    return validate_rate(value, model)


def dollars(cfg: Config, usage: tuple[Usage, ...]) -> float:
    total = 0.0
    for row in usage:
        label = f"thread {row.thread!r}, model {row.model!r}"
        if row.unavailable is not None:
            raise Unpriced(f"{label}: {row.unavailable or 'billing evidence unavailable'}")
        for name in ("input", "cached_input", "output", "cache_write_30m", "cache_write_12h"):
            count = getattr(row, name)
            if count is None:
                raise Unpriced(f"{label}: {name} unavailable")
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise Unpriced(f"{label}: {name} must be a nonnegative integer")
        uncached = row.input - row.cached_input - row.cache_write_30m - row.cache_write_12h
        if uncached < 0:
            raise Unpriced(f"{label}: cache input categories exceed inclusive input")
        prices = rate(cfg, row.model)
        for name in ("cache_write_30m", "cache_write_12h"):
            if getattr(row, name) and getattr(prices, name) is None:
                raise Unpriced(f"{label}: required {name} rate unavailable")
        try:
            total += (
                uncached * prices.input
                + row.cached_input * prices.cached_input
                + row.cache_write_30m * (prices.cache_write_30m or 0)
                + row.cache_write_12h * (prices.cache_write_12h or 0)
                + row.output * prices.output
            ) / 1_000_000
        except OverflowError as exc:
            raise Unpriced(f"{label}: cost exceeds numeric range") from exc
        if not isfinite(total):
            raise Unpriced(f"{label}: cost exceeds numeric range")
    return total
