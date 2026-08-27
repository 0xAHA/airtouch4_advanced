"""Tests for AirtouchBroadcastListener's echo-suppression / refresh logic.

Covers the #9 fix: the AirTouch4 console echoes its status broadcasts to
every connected client, including this listener's own persistent
connection, as a side effect of the coordinator's ordinary polling. Left
unguarded that's a feedback loop - our own poll's echo looks like an
external change, triggers another refresh, whose echo triggers another,
and so on. These tests exercise the two independent guards against that
without needing real AirTouch4 hardware: echo suppression (a broadcast
arriving right after our own poll activity is ignored) and a minimum
interval between listener-triggered refreshes (a backstop).
"""

import asyncio
import time

import pytest

from conftest import listener_module

AirtouchBroadcastListener = listener_module.AirtouchBroadcastListener


class FakeCoordinator:
    """Stand-in for AirtouchDataUpdateCoordinator's timing + refresh API."""

    def __init__(self, last_poll_activity_at: float = 0.0):
        self.last_poll_activity_at = last_poll_activity_at
        self.refresh_calls: list[float] = []

    async def async_request_refresh(self) -> None:
        self.refresh_calls.append(time.monotonic())


class FakeHass:
    """Stand-in for the bits of hass the listener touches."""

    def __init__(self):
        self.loop = asyncio.get_event_loop()

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    """Shrink the real-time delays so tests run in well under a second."""
    monkeypatch.setattr(listener_module, "REFRESH_DEBOUNCE", 0.05)
    monkeypatch.setattr(listener_module, "MIN_REFRESH_INTERVAL", 0.2)
    monkeypatch.setattr(listener_module, "ECHO_SUPPRESSION_WINDOW", 0.2)


def make_listener(coordinator) -> AirtouchBroadcastListener:
    return AirtouchBroadcastListener(FakeHass(), coordinator, "127.0.0.1")


async def test_broadcast_far_from_any_poll_triggers_refresh():
    """A broadcast with no recent poll activity looks like a real change."""
    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic() - 999)
    listener = make_listener(coordinator)

    listener._schedule_refresh()
    await asyncio.sleep(0.15)

    assert len(coordinator.refresh_calls) == 1


async def test_broadcast_right_after_poll_is_suppressed_as_echo():
    """A broadcast landing right after our own poll is assumed to be its echo."""
    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic())
    listener = make_listener(coordinator)

    listener._schedule_refresh()
    await asyncio.sleep(0.15)

    assert coordinator.refresh_calls == []


async def test_broadcast_outside_suppression_window_is_not_treated_as_echo():
    """Once enough time has passed since the poll, broadcasts are trusted again."""
    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic())
    listener = make_listener(coordinator)

    # Wait past ECHO_SUPPRESSION_WINDOW (0.2s) before the broadcast arrives.
    await asyncio.sleep(0.25)
    listener._schedule_refresh()
    await asyncio.sleep(0.15)

    assert len(coordinator.refresh_calls) == 1


async def test_burst_of_broadcasts_still_coalesces_into_one_refresh():
    """Pre-existing debounce behaviour: rapid repeats collapse to one refresh."""
    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic() - 999)
    listener = make_listener(coordinator)

    for _ in range(5):
        listener._schedule_refresh()
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)

    assert len(coordinator.refresh_calls) == 1


async def test_feedback_loop_is_broken_by_echo_suppression(monkeypatch):
    """
    Simulates the reported bug directly: each refresh "causes" a poll, whose
    echo arrives back at the listener almost immediately. Without echo
    suppression this free-runs; with it, the chain dies after the first hop.

    MIN_REFRESH_INTERVAL is disabled here so this test isolates echo
    suppression specifically, rather than incidentally passing via the
    backstop floor (which is covered on its own below).
    """
    monkeypatch.setattr(listener_module, "MIN_REFRESH_INTERVAL", 0)
    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic() - 999)
    listener = make_listener(coordinator)

    async def poll_and_echo_on_refresh():
        # Stand in for the coordinator's own update cycle: stamp poll
        # activity (as _async_update_data's try/finally does), then the
        # console echoes it straight back to the listener.
        coordinator.last_poll_activity_at = time.monotonic()
        listener._schedule_refresh()

    real_request_refresh = coordinator.async_request_refresh

    async def request_refresh_and_chain():
        await real_request_refresh()
        await poll_and_echo_on_refresh()

    coordinator.async_request_refresh = request_refresh_and_chain

    # Kick off the loop with one genuine external broadcast.
    listener._schedule_refresh()
    await asyncio.sleep(0.3)

    assert len(coordinator.refresh_calls) == 1


async def test_min_refresh_interval_backstops_rapid_distinct_triggers():
    """Two non-echo broadcasts spaced closer than MIN_REFRESH_INTERVAL: only one fires."""
    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic() - 999)
    listener = make_listener(coordinator)

    listener._schedule_refresh()
    await asyncio.sleep(0.1)  # let debounce fire, past REFRESH_DEBOUNCE (0.05s)

    listener._schedule_refresh()
    await asyncio.sleep(0.1)  # still within MIN_REFRESH_INTERVAL (0.2s) of the first

    assert len(coordinator.refresh_calls) == 1

    # After the floor elapses, a further broadcast is trusted again.
    await asyncio.sleep(0.2)
    listener._schedule_refresh()
    await asyncio.sleep(0.1)

    assert len(coordinator.refresh_calls) == 2
