"""DataUpdateCoordinator for the AirTouch4 integration."""
import logging

from airtouch4pyapi.airtouch import AirTouchStatus
from homeassistant.components.climate import SCAN_INTERVAL
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class AirtouchDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching AirTouch data."""

    def __init__(self, hass, airtouch):
        """Initialize global AirTouch data updater."""
        self.airtouch = airtouch
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Fetch data from AirTouch."""
        await self.airtouch.UpdateInfo()
        if self.airtouch.Status != AirTouchStatus.OK:
            raise UpdateFailed("AirTouch connection issue")
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
                for ac in self.airtouch.GetAcs()
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
                for group in self.airtouch.GetGroups()
            ],
        }
