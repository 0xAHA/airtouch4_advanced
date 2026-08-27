"""DataUpdateCoordinator for the AirTouch4 integration."""
import logging
import time

from airtouch4pyapi.airtouch import AirTouchStatus
from homeassistant.components.climate import SCAN_INTERVAL
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Number of consecutive failed updates after which the AirTouch client is
# recreated from scratch, in case a failed exchange left it in a poisoned
# half-initialised state that a fresh UpdateInfo() call can't recover from.
RECONNECT_AFTER_FAILURES = 3

class AirtouchDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching AirTouch data."""

    def __init__(self, hass, airtouch, host):
        """Initialize global AirTouch data updater."""
        self.airtouch = airtouch
        self._host = host
        self._consecutive_failures = 0
        # monotonic timestamp of the most recent poll activity (set at both
        # the start and end of _async_update_data). Used by the broadcast
        # listener to recognise its own poll's echo and avoid retriggering
        # itself - see AirtouchBroadcastListener.
        self.last_poll_activity_at: float = 0.0
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    def _register_failure(self):
        """Track consecutive failures and recreate the client if it's likely poisoned."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= RECONNECT_AFTER_FAILURES:
            _LOGGER.warning(
                "AirTouch at %s failed %d consecutive updates; recreating connection",
                self._host,
                self._consecutive_failures,
            )
            from airtouch4pyapi.airtouch import AirTouch

            self.airtouch = AirTouch(self._host)
            self._consecutive_failures = 0

    async def _async_update_data(self):
        """Fetch data from AirTouch."""
        # Stamped at both start and end: the console echoes broadcast
        # packets to every connected client - including the listener's
        # persistent connection - as a side effect of handling this very
        # exchange, so the "activity window" covers the whole poll, not
        # just its completion instant.
        self.last_poll_activity_at = time.monotonic()
        try:
            try:
                await self.airtouch.UpdateInfo()
                if self.airtouch.Status != AirTouchStatus.OK:
                    raise UpdateFailed("AirTouch connection issue")
            except UpdateFailed:
                self._register_failure()
                raise
            except Exception as err:
                self._register_failure()
                raise UpdateFailed(f"Error communicating with AirTouch: {err}") from err

            acs = self.airtouch.GetAcs()
            groups = self.airtouch.GetGroups()

            # A "successful" UpdateInfo() can still hand back a hollow/partial
            # read (e.g. zero groups) with no exception and no bad Status - seen
            # in the wild as a transient false "off" state. If we previously had
            # groups and this cycle suddenly has none, treat it as a failed
            # cycle rather than publishing bogus state.
            had_groups_before = bool(self.data and self.data.get("groups"))
            if had_groups_before and not groups:
                self._register_failure()
                raise UpdateFailed(
                    "AirTouch returned no zones on this poll; skipping cycle"
                )

            self._consecutive_failures = 0
            return {
                "acs": [
                    {
                        "ac_number": ac.AcNumber,
                        "ac_name": getattr(ac, "AcName", f"AC {ac.AcNumber}"),
                        "is_on": ac.IsOn,
                        "power_state": getattr(ac, "PowerState", "Off"),
                        "ac_mode": getattr(ac, "AcMode", "Fan"),
                        "fan_speed": getattr(ac, "AcFanSpeed", "Auto"),
                        "temperature": getattr(ac, "Temperature", None),
                        "min_setpoint": getattr(ac, "MinSetpoint", 16),
                        "max_setpoint": getattr(ac, "MaxSetpoint", 30),
                    }
                    for ac in acs
                ],
                "groups": [
                    {
                        "group_number": group.GroupNumber,
                        "group_name": group.GroupName,
                        "is_on": group.IsOn,
                        "power_state": getattr(group, "PowerState", "Off"),
                        # DON'T BE TEMPTED TO TRY WITH OPENPERCENT.... ONLY OPENPERCENTAGE!!!!!!
                        "open_percent": getattr(group, "OpenPercentage", 0),
                        "control_method": getattr(group, "ControlMethod", "Unknown"),
                        "temperature": getattr(group, "Temperature", None),
                        "target_setpoint": getattr(group, "TargetSetpoint", None),
                    }
                    for group in groups
                ],
            }
        finally:
            self.last_poll_activity_at = time.monotonic()
