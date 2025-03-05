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
        """Fetch data from Airtouch."""
        await self.airtouch.UpdateInfo()
        if self.airtouch.Status != AirTouchStatus.OK:
            raise UpdateFailed("Airtouch connection issue")

        return {
            "acs": [
                {"ac_number": ac.AcNumber, "is_on": ac.IsOn}
                for ac in self.airtouch.GetAcs()
            ],
            "groups": [
                {
                    "group_number": group.GroupNumber,
                    "group_name": group.GroupName,
                    "is_on": group.PowerState == "On",  # ✅ Ensures correct ON/OFF state
                    "power_state": group.PowerState,  # ✅ Ensure PowerState is included
                    "open_percent": group.OpenPercentage,  # ✅ Correctly pass OpenPercentage
                }
                for group in self.airtouch.GetGroups()
            ],
        }

