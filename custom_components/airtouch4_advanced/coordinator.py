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

# Number of consecutive hollow-temperature reads tolerated for a single AC
# before it's treated as a genuine failure rather than a benign one-poll
# reporting gap. Below this, the AC's previous known-good snapshot is reused
# ("repaired") and the cycle still succeeds; at or above it, the cycle is
# rejected like any other failure. Mirrors RECONNECT_AFTER_FAILURES's
# 3-strike pattern.
AC_HOLLOW_REPAIR_LIMIT = 3

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
        # Per-AC (by ac_number) count of consecutive hollow-temperature
        # reads - see AC_HOLLOW_REPAIR_LIMIT and the repair logic below.
        self._ac_hollow_streak: dict[int, int] = {}
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

            # Same failure mode, symmetric case: the AC-status portion of a
            # cycle can go hollow while groups parse fine (and vice versa) -
            # the two exchanges apparently fail independently. Total AC
            # dropout mirrors the zones check above:
            had_acs_before = bool(self.data and self.data.get("acs"))
            if had_acs_before and not acs:
                self._register_failure()
                raise UpdateFailed(
                    "AirTouch returned no AC units on this poll; skipping cycle"
                )

            # Narrower case, confirmed in the field (#4): groups and the AC
            # list both parse, but an individual AC's own status is hollow -
            # Temperature reads None where the previous cycle had a real
            # value, with IsOn/PowerState defaulting to "off" alongside it.
            # This is the AC-status exchange specifically returning a
            # wrong/empty payload; compared per-AC (by ac_number) rather than
            # "any AC still looks fine", so a hollow read on one AC in a
            # multi-AC system isn't masked by another AC that's still healthy.
            # Temperature-only, deliberately: PowerState/IsOn alone can't be
            # used as a hollow signal since a genuinely-off AC looks the same.
            #
            # Field data showed this guard's original reject-the-cycle
            # behaviour firing far more often than genuine connection
            # failures (the console appears to legitimately omit AC
            # temperature on some polls, not just during real corruption),
            # and rejecting flips every entity unavailable for ~60s each
            # time. So: repair a hollow AC from its last known snapshot and
            # let the cycle succeed for the first AC_HOLLOW_REPAIR_LIMIT
            # consecutive hollow reads on that AC; only reject the cycle
            # once that streak is exceeded, by which point it looks like a
            # genuine problem rather than a one-poll reporting gap.
            previous_acs_by_number = {
                ac_data["ac_number"]: ac_data
                for ac_data in (self.data or {}).get("acs", [])
            }

            ac_dicts = []
            for ac in acs:
                ac_dict = {
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

                previous = previous_acs_by_number.get(ac.AcNumber)
                is_hollow = (
                    previous is not None
                    and previous.get("temperature") is not None
                    and ac_dict["temperature"] is None
                )
                if not is_hollow:
                    self._ac_hollow_streak.pop(ac.AcNumber, None)
                    ac_dicts.append(ac_dict)
                    continue

                streak = self._ac_hollow_streak.get(ac.AcNumber, 0) + 1
                self._ac_hollow_streak[ac.AcNumber] = streak
                if streak >= AC_HOLLOW_REPAIR_LIMIT:
                    self._register_failure()
                    raise UpdateFailed(
                        f"AirTouch AC {ac.AcNumber} status looks hollow on "
                        f"this poll ({streak} in a row); skipping cycle"
                    )

                _LOGGER.debug(
                    "AirTouch AC %s temperature read hollow (streak %d/%d); "
                    "repairing from last known value (%s) instead of "
                    "failing the cycle",
                    ac.AcNumber,
                    streak,
                    AC_HOLLOW_REPAIR_LIMIT,
                    previous.get("temperature"),
                )
                ac_dicts.append(previous)

            self._consecutive_failures = 0
            return {
                "acs": ac_dicts,
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
