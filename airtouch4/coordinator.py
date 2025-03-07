"""DataUpdateCoordinator for the airtouch integration."""

import logging
from datetime import timedelta

from airtouch4pyapi.airtouch import AirTouchStatus

from homeassistant.components.climate import SCAN_INTERVAL
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=10)

class AirtouchDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Airtouch data."""

    def __init__(self, hass, airtouch):
        """Initialize global Airtouch data updater."""
        self.airtouch = airtouch

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Fetch data from Airtouch with extra debug logs to confirm open_percent."""
        await self.airtouch.UpdateInfo()

        if self.airtouch.Status != AirTouchStatus.OK:
            raise UpdateFailed("Airtouch connection issue")

        # Build the AC and group data structures
        ac_list = self.airtouch.GetAcs()
        group_list = self.airtouch.GetGroups()

        # Log raw data from the library
        _LOGGER.debug("Coordinator _async_update_data: Raw AC list from library: %s", ac_list)
        _LOGGER.debug("Coordinator _async_update_data: Raw Group list from library: %s", group_list)

        # Construct dictionary-based data for HA
        acs_data = []
        for ac in ac_list:
            ac_entry = {
                "ac_number": ac.AcNumber,
                "ac_name": getattr(ac, "AcName", f"AC {ac.AcNumber}"),
                "is_on": ac.IsOn,
                "power_state": getattr(ac, "PowerState", "Unknown"),
                "ac_mode": getattr(ac, "AcMode", "Unknown"),
                "fan_speed": getattr(ac, "AcFanSpeed", "Auto"),
                "temperature": getattr(ac, "Temperature", None),
                "min_setpoint": getattr(ac, "MinSetpoint", None),
                "max_setpoint": getattr(ac, "MaxSetpoint", None),
            }
            acs_data.append(ac_entry)

        groups_data = []
        for group in group_list:
            group_entry = {
                "group_number": group.GroupNumber,
                "group_name": group.GroupName,
                "is_on": group.IsOn,
                "power_state": getattr(group, "PowerState", "Unknown"),
                "open_percent": getattr(group, "OpenPercentage", 0),
                "control_method": getattr(group, "ControlMethod", "Unknown"),
                "temperature": getattr(group, "Temperature", None),
                "target_setpoint": getattr(group, "TargetSetpoint", None),
            }
            groups_data.append(group_entry)

        # Log final dictionary data
        _LOGGER.debug("Coordinator _async_update_data: Final AC data for HA: %s", acs_data)
        _LOGGER.debug("Coordinator _async_update_data: Final Group data for HA: %s", groups_data)

        return {
            "acs": acs_data,
            "groups": groups_data,
        }




