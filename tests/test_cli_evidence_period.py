"""`evidence export` takes the period an auditor actually asks for.

The HTTP API has always taken an explicit period; the CLI only had a lookback in days,
so the README's own example did not run. These tests pin the behaviour that makes a
signed package trustworthy: the range is what was asked for, a bare end date covers that
whole day, and an impossible range is refused rather than quietly reinterpreted.
"""

from __future__ import annotations

import datetime as dt

import pytest
import typer

from agentfox.cli.commands.audit import _evidence_period


def test_no_range_falls_back_to_the_lookback():
    start, end = _evidence_period(None, None, 30)
    assert end is None  # left to evidence.build, which uses "now"
    assert 29.9 < (dt.datetime.now(dt.UTC) - start).total_seconds() / 86400 < 30.1


def test_explicit_range_is_used_verbatim():
    start, end = _evidence_period("2026-08-01", "2026-08-17", 30)
    assert start == dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
    assert start.tzinfo is dt.UTC and end.tzinfo is dt.UTC


def test_a_bare_end_date_covers_that_whole_day():
    _start, end = _evidence_period("2026-08-01", "2026-08-17", 30)
    assert end == dt.datetime(2026, 8, 17, 23, 59, 59, 999999, tzinfo=dt.UTC)
    # A day of evidence must not be dropped from a package someone signs.
    assert end.date() == dt.date(2026, 8, 17)


def test_a_full_timestamp_is_honoured_to_the_second():
    start, end = _evidence_period("2026-08-01T06:30:00", "2026-08-17T09:15:00", 30)
    assert (start.hour, start.minute) == (6, 30)
    assert (end.hour, end.minute) == (9, 15)


def test_from_alone_ends_now_and_to_alone_still_looks_back():
    start, end = _evidence_period("2026-08-01", None, 30)
    assert start == dt.datetime(2026, 8, 1, tzinfo=dt.UTC) and end is not None
    start, end = _evidence_period(None, "2026-08-17", 7)
    assert (end - start).days == 7


@pytest.mark.parametrize("bad", ["last tuesday", "2026-13-40", ""])
def test_unparseable_dates_are_refused(bad):
    with pytest.raises(typer.BadParameter):
        _evidence_period(bad, None, 30)


def test_a_backwards_range_is_refused():
    with pytest.raises(typer.BadParameter):
        _evidence_period("2026-09-01", "2026-08-01", 30)
