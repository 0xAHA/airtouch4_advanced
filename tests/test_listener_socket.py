"""End-to-end test of AirtouchBroadcastListener against a real local socket.

Complements test_listener.py's direct calls to _schedule_refresh() by
exercising the actual connect/read loop (start/_listen_once/stop) against a
fake local TCP server standing in for the AirTouch4 console, to catch bugs
that only show up in the real asyncio plumbing (e.g. in BROADCAST_PORT
wiring, connection teardown, or the reader loop itself).
"""

import asyncio
import time

import pytest

from conftest import listener_module

AirtouchBroadcastListener = listener_module.AirtouchBroadcastListener


class FakeCoordinator:
    def __init__(self, last_poll_activity_at: float = 0.0):
        self.last_poll_activity_at = last_poll_activity_at
        self.refresh_calls: list[float] = []

    async def async_request_refresh(self) -> None:
        self.refresh_calls.append(time.monotonic())


class FakeHass:
    def __init__(self):
        self.loop = asyncio.get_event_loop()

    def async_create_task(self, coro):
        return self.loop.create_task(coro)


@pytest.fixture(autouse=True)
def fast_timings(monkeypatch):
    monkeypatch.setattr(listener_module, "REFRESH_DEBOUNCE", 0.05)
    monkeypatch.setattr(listener_module, "MIN_REFRESH_INTERVAL", 0.2)
    monkeypatch.setattr(listener_module, "ECHO_SUPPRESSION_WINDOW", 0.2)
    monkeypatch.setattr(listener_module, "RECONNECT_DELAY", 0.05)


@pytest.fixture
async def fake_console():
    """A minimal TCP server standing in for the AirTouch4 console's broadcast port."""
    connections: list[asyncio.StreamWriter] = []
    client_connected = asyncio.Event()

    async def handle_client(reader, writer):
        connections.append(writer)
        client_connected.set()
        try:
            # Keep the connection open until the test (or its peer) tears it down.
            await reader.read(-1)
        except asyncio.CancelledError:
            pass
        finally:
            # Python 3.12+ changed Server.wait_closed() to also wait for
            # already-accepted connections to close, not just the listening
            # socket - explicitly closing here (rather than relying on the
            # handler's return to do it implicitly) avoids wait_closed()
            # hanging below if that connection is still considered open.
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    yield port, connections, client_connected

    server.close()
    # Same Python 3.12+ concern as above, from the other side: bound this
    # so a connection that somehow never closes fails the test loudly
    # instead of hanging CI indefinitely.
    await asyncio.wait_for(server.wait_closed(), timeout=5)


async def test_real_socket_echo_right_after_poll_is_suppressed(monkeypatch, fake_console):
    port, connections, client_connected = fake_console
    monkeypatch.setattr(listener_module, "BROADCAST_PORT", port)

    coordinator = FakeCoordinator(last_poll_activity_at=0.0)
    listener = AirtouchBroadcastListener(FakeHass(), coordinator, "127.0.0.1")
    listener.start()

    await asyncio.wait_for(client_connected.wait(), timeout=2)

    # Simulate the coordinator having just finished a poll, then the
    # console echoing that exchange down the held-open broadcast socket.
    coordinator.last_poll_activity_at = time.monotonic()
    connections[0].write(b"\x01\x02\x03echo")
    await connections[0].drain()

    await asyncio.sleep(0.3)
    assert coordinator.refresh_calls == []

    await listener.stop()


async def test_real_socket_broadcast_with_no_recent_poll_triggers_refresh(
    monkeypatch, fake_console
):
    port, connections, client_connected = fake_console
    monkeypatch.setattr(listener_module, "BROADCAST_PORT", port)

    coordinator = FakeCoordinator(last_poll_activity_at=time.monotonic() - 999)
    listener = AirtouchBroadcastListener(FakeHass(), coordinator, "127.0.0.1")
    listener.start()

    await asyncio.wait_for(client_connected.wait(), timeout=2)

    connections[0].write(b"\x01\x02\x03external-change")
    await connections[0].drain()

    await asyncio.sleep(0.3)
    assert len(coordinator.refresh_calls) == 1

    await listener.stop()
