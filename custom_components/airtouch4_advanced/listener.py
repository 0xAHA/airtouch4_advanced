"""Push-notification listener for AirTouch4 status broadcasts.

The AirTouch4 console pushes a status packet to any client holding an open
TCP connection whenever a zone/AC is changed from the AirTouch app or a wall
panel. ``airtouch4pyapi`` opens a fresh socket per request/response exchange
and closes it immediately, so it is never connected when the console
broadcasts a change - external changes are only picked up on the next
``SCAN_INTERVAL`` poll (up to 60s later).

This listener holds a persistent connection purely to notice *that*
something changed. It does not parse the AirTouch4 binary protocol - any
inbound bytes are treated as a signal to ask the coordinator for a fresh
poll via the existing, already-parsed ``airtouch4pyapi`` request/response
path. If the connection can't be established or drops, it retries with a
fixed delay and otherwise has no effect on the integration, which keeps
working via its normal polling.
"""

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

BROADCAST_PORT = 9004
RECONNECT_DELAY = 10  # seconds between reconnect attempts
REFRESH_DEBOUNCE = 1  # seconds to coalesce bursts of broadcast packets


class AirtouchBroadcastListener:
    """Holds an open socket to the AirTouch4 console and triggers refreshes."""

    def __init__(self, hass, coordinator, host: str):
        self._hass = hass
        self._coordinator = coordinator
        self._host = host
        self._task: asyncio.Task | None = None
        self._refresh_handle: asyncio.TimerHandle | None = None
        self._stopped = False

    def start(self) -> None:
        """Start the background listener task."""
        self._stopped = False
        self._task = self._hass.loop.create_task(self._run())

    async def stop(self) -> None:
        """Stop the background listener task."""
        self._stopped = True
        if self._refresh_handle:
            self._refresh_handle.cancel()
            self._refresh_handle = None
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.debug(
                    "AirTouch broadcast listener for %s disconnected: %s",
                    self._host,
                    err,
                )
            if self._stopped:
                return
            await asyncio.sleep(RECONNECT_DELAY)

    async def _listen_once(self) -> None:
        _LOGGER.debug(
            "Connecting AirTouch broadcast listener to %s:%s", self._host, BROADCAST_PORT
        )
        reader, writer = await asyncio.open_connection(self._host, BROADCAST_PORT)
        try:
            _LOGGER.debug("AirTouch broadcast listener connected to %s", self._host)
            while not self._stopped:
                data = await reader.read(1024)
                if not data:
                    _LOGGER.debug(
                        "AirTouch broadcast connection to %s closed by remote", self._host
                    )
                    return
                _LOGGER.debug(
                    "AirTouch broadcast received from %s (%d bytes); requesting refresh",
                    self._host,
                    len(data),
                )
                self._schedule_refresh()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _schedule_refresh(self) -> None:
        """Debounce bursts of broadcast packets into a single refresh."""
        if self._refresh_handle:
            self._refresh_handle.cancel()
        self._refresh_handle = self._hass.loop.call_later(
            REFRESH_DEBOUNCE, self._trigger_refresh
        )

    def _trigger_refresh(self) -> None:
        self._hass.async_create_task(self._coordinator.async_request_refresh())
