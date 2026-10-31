"""Cache billing contract: relay-cache-cost-design.md, Modules pricing."""

from dataclasses import replace

import pytest

from relay.pricing import Rate, Unpriced, Usage, dollars, rate


def test_standard_rates_cover_each_exact_model(fake_cfg):
    # Breaks when any documented standard model loses its distinct rates.
    expected = {
        "gpt-6-astra": Rate(10, 1, 50, 12.5, 25),
        "gpt-6.1-sol": Rate(2, 0.1, 10, 2.5, 5),
        "gpt-6.1-terra": Rate(1, 0.05, 5, 1.25, 2.5),
        "gpt-6-luna": Rate(0.1, 0.01, 0.5, 0.125, 0.25),
    }
    assert {model: rate(fake_cfg, model) for model in expected} == expected


def test_category_charges_replace_uncached_input(fake_cfg):
    # Breaks when reads or either write duration is also billed as uncached input.
    cfg = replace(fake_cfg, prices={"custom": Rate(7, 2, 19, 11, 23)})
    rows = (
        (Usage("t", "custom", 1_000_000, 0, 0), 7),
        (Usage("t", "custom", 1_000_000, 1_000_000, 0), 2),
        (Usage("t", "custom", 1_000_000, 0, 0, 1_000_000), 11),
        (Usage("t", "custom", 1_000_000, 0, 0, 0, 1_000_000), 23),
        (Usage("t", "custom", 0, 0, 1_000_000), 19),
    )
    for usage, expected in rows:
        assert dollars(cfg, (usage,)) == pytest.approx(expected)


def test_mixed_categories_and_inclusive_reasoning_are_charged_once(fake_cfg):
    # Breaks when mixed cache categories overlap or output including reasoning doubles.
    cfg = replace(fake_cfg, prices={"custom": Rate(7, 2, 19, 11, 23)})
    usage = Usage("t", "custom", 1_000_000, 200_000, 500_000, 300_000, 100_000)
    assert dollars(cfg, (usage,)) == pytest.approx(18.3)


def test_rows_sum_with_their_own_model_and_thread_rates(fake_cfg):
    # Breaks when a later model's rate replaces earlier rows or only one thread counts.
    cfg = replace(fake_cfg, prices={"first": Rate(3, 1, 5), "second": Rate(13, 2, 17)})
    rows = (
        Usage("lead", "first", 1_000_000, 200_000, 100_000),
        Usage("child", "second", 500_000, 100_000, 200_000),
    )
    assert dollars(cfg, rows) == pytest.approx(11.9)


def test_custom_rate_precedence_and_legacy_construction(fake_cfg):
    # Breaks when built-ins override custom rates or legacy zero writes require write rates.
    custom = Rate(3, 1, 5)
    cfg = replace(fake_cfg, prices={"gpt-6.1-sol": custom})
    assert rate(cfg, "gpt-6.1-sol") == custom
    assert dollars(cfg, (Usage("t", "gpt-6.1-sol", 1_000_000, 200_000, 100_000),)) == pytest.approx(
        3.1
    )
    free = replace(fake_cfg, prices={"free": Rate(0, 0, 0, 0, 0)})
    assert dollars(free, (Usage("t", "free", 10, 2, 3, 2, 2),)) == 0


def test_unknown_model_never_borrows_a_rate(fake_cfg):
    # Breaks when unknown model names inherit a known model or default rate.
    for model in ("gpt-6.1-sol-extra", "unlisted"):
        with pytest.raises(Unpriced, match=".+"):
            rate(fake_cfg, model)
        with pytest.raises(Unpriced, match=".+"):
            dollars(fake_cfg, (Usage("t", model, 1, 0, 0),))


def test_zero_and_empty_usage_are_numeric_zero(fake_cfg):
    # Breaks when a known zero becomes unavailable or an empty invocation is charged.
    assert dollars(fake_cfg, ()) == 0
    assert dollars(fake_cfg, (Usage("t", "gpt-6.1-sol", 0, 0, 0),)) == 0


def test_nonzero_writes_require_the_corresponding_rate(fake_cfg):
    # Breaks when unavailable write rates silently fall back to input or read pricing.
    cfg = replace(fake_cfg, prices={"custom": Rate(3, 1, 5)})
    for fields in ({"cache_write_30m": 1}, {"cache_write_12h": 1}):
        with pytest.raises(Unpriced, match=".+"):
            dollars(cfg, (Usage("t", "custom", 10, 0, 0, **fields),))


def test_unavailable_billing_dimensions_never_become_numeric_cost(fake_cfg):
    # Breaks when missing read/write evidence or an unknown billing regime is assumed zero.
    base = Usage("t", "gpt-6.1-sol", 10, 0, 2)
    for fields in (
        {"cached_input": None},
        {"cache_write_30m": None},
        {"cache_write_12h": None},
        {"unavailable": "unknown write bucket"},
        {"unavailable": "unsupported long-context regime"},
    ):
        with pytest.raises(Unpriced, match=".+"):
            dollars(fake_cfg, (replace(base, **fields),))


def test_counts_are_nonnegative_integers_excluding_booleans(fake_cfg):
    # Breaks when a malformed count is clamped, coerced, or accepted as billing evidence.
    base = Usage("t", "gpt-6.1-sol", 100, 10, 2)
    for field in ("input", "cached_input", "output", "cache_write_30m", "cache_write_12h"):
        for value in (-1, True, 1.5, "1", float("inf"), float("nan")):
            with pytest.raises(Unpriced, match=".+"):
                dollars(fake_cfg, (replace(base, **{field: value}),))


def test_input_categories_cannot_overlap_or_exceed_input(fake_cfg):
    # Breaks when excess cached categories are clamped or a negative uncached charge is allowed.
    for usage in (Usage("t", "gpt-6.1-sol", 10, 11, 0), Usage("t", "gpt-6.1-sol", 10, 5, 0, 4, 2)):
        with pytest.raises(Unpriced, match=".+"):
            dollars(fake_cfg, (usage,))


def test_direct_rates_must_be_finite_nonnegative_numbers(fake_cfg):
    # Breaks when invalid custom rates bypass configuration and produce false costs.
    for field in ("input", "cached_input", "output", "cache_write_30m", "cache_write_12h"):
        for value in (-1, True, "1", float("inf"), float("nan")):
            bad = replace(Rate(3, 1, 5, 7, 11), **{field: value})
            cfg = replace(fake_cfg, prices={"custom": bad})
            with pytest.raises(Unpriced, match=".+"):
                dollars(cfg, (Usage("t", "custom", 10, 2, 3, 2, 2),))


def test_one_unpriceable_row_prevents_a_partial_numeric_total(fake_cfg):
    # Breaks when invalid rows are skipped while a misleading partial total is returned.
    rows = (
        Usage("valid", "gpt-6.1-sol", 100, 0, 1),
        Usage("missing", "gpt-6.1-sol", 100, 0, 1, None),
    )
    with pytest.raises(Unpriced, match=".+"):
        dollars(fake_cfg, rows)
