from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from app.engine.events import (
    Observation,
    detect_price_events,
    detect_score_events,
    should_store_observation,
    should_store_score,
)

T = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def obs(price, availability="in_stock", at=T, mrp=None, seller="S"):
    return Observation(None if price is None else D(price), availability, at, mrp and D(mrp), seller)


# ------------------------------------------------------------ storing observations
def test_first_observation_is_stored():
    assert should_store_observation(None, obs(100))


def test_unchanged_observation_is_skipped_until_heartbeat():
    prev = obs(100, at=T)
    assert not should_store_observation(prev, obs(100, at=T + timedelta(minutes=30)))
    assert should_store_observation(prev, obs(100, at=T + timedelta(hours=6)))


@pytest.mark.parametrize(
    "new",
    [obs(99), obs(100, mrp=120), obs(None, "out_of_stock"), obs(100, seller="Other")],
)
def test_any_meaningful_change_is_stored(new):
    assert should_store_observation(obs(100), Observation(new.price, new.availability, T + timedelta(minutes=1), new.mrp, new.seller_name))


# ------------------------------------------------------------ price events
def test_price_drop_detected():
    ev = detect_price_events(obs(1000), obs(900), None, False)
    assert [e.event_type for e in ev] == ["price_drop"]
    assert ev[0].previous_price == 1000 and ev[0].detail["drop_pct"] == 10.0


def test_tiny_drop_ignored():
    assert detect_price_events(obs(1000), obs(995), None, False) == []


def test_price_increase_is_not_an_event():
    assert detect_price_events(obs(1000), obs(1100), None, True) == []


def test_historical_low_needs_history_and_a_drop():
    ev = detect_price_events(obs(1000), obs(850), D(900), has_sufficient_history=True)
    assert {e.event_type for e in ev} == {"price_drop", "historical_low"}
    low = next(e for e in ev if e.event_type == "historical_low")
    assert low.detail["is_new_low"] is True

    no_history = detect_price_events(obs(1000), obs(850), D(900), has_sufficient_history=False)
    assert {e.event_type for e in no_history} == {"price_drop"}


def test_close_to_previous_low_counts_but_is_not_a_new_low():
    ev = detect_price_events(obs(1000), obs(905), D(900), True)  # within 1%
    low = next(e for e in ev if e.event_type == "historical_low")
    assert low.detail["is_new_low"] is False


def test_drop_far_above_low_is_not_historical_low():
    ev = detect_price_events(obs(1500), obs(1200), D(900), True)
    assert {e.event_type for e in ev} == {"price_drop"}


def test_back_in_stock():
    ev = detect_price_events(obs(None, "out_of_stock"), obs(1000), None, False)
    assert [e.event_type for e in ev] == ["back_in_stock"]


def test_no_events_when_new_observation_unavailable_or_first():
    assert detect_price_events(obs(1000), obs(None, "out_of_stock"), None, True) == []
    assert detect_price_events(None, obs(1000), None, True) == []


# ------------------------------------------------------------ score events
def test_new_deal_when_crossing_threshold():
    assert [e.event_type for e in detect_score_events(None, 75)] == ["new_deal"]
    assert [e.event_type for e in detect_score_events(60, 72)] == ["new_deal"]


def test_no_repeat_while_still_a_deal():
    assert detect_score_events(72, 85) == []


def test_deal_expiry_uses_hysteresis():
    assert detect_score_events(75, 68) == []  # dipped, but not below the expiry bar
    assert [e.event_type for e in detect_score_events(75, 62)] == ["deal_expired"]


def test_no_score_no_event():
    assert detect_score_events(80, None) == []


# ------------------------------------------------------------ storing scores
def test_score_storage_rules():
    old = T - timedelta(hours=1)
    assert should_store_score(None, None, 50, T)
    assert not should_store_score(50, old, 50.2, T)
    assert should_store_score(50, old, 51, T)
    assert should_store_score(50, old, None, T)  # became unscorable
    assert should_store_score(50, T - timedelta(hours=25), 50, T)  # heartbeat
