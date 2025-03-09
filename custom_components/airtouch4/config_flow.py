import asyncio
import logging
from typing import Any, Dict

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector

from airtouch4pyapi import AirTouch, AirTouchStatus  # Adjust if needed

from .const import DOMAIN, MODE_DEFAULT, MODE_NONITC_FAN, MODE_NONITC_CLIMATE  # Imported from const.py

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
    }
)

class AirtouchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirTouch4 with advanced non-ITC zone setup."""

    VERSION = 2

    def __init__(self):
        self._host = None
        self._discovered_zones = []
        self._non_itc_zones = []
        self._setup_mode = MODE_DEFAULT
        self._temp_sensors: Dict[int, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an options flow if needed (not implemented here)."""
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """First step: user enters the host IP + device connection check."""
        errors = {}

        try:
            _LOGGER.debug("Entered async_step_user with user_input=%s", user_input)

            if user_input is not None:
                host = user_input[CONF_HOST]
                self._async_abort_entries_match({CONF_HOST: host})

                _LOGGER.debug("Attempting to connect to AirTouch at %s", host)
                airtouch = AirTouch(host)
                await airtouch.UpdateInfo()

                if airtouch.Status != AirTouchStatus.OK:
                    errors["base"] = "cannot_connect"
                else:
                    # Store host, discover zones, etc.
                    self._host = host
                    self._discovered_zones = airtouch.GetGroups()
                    self._non_itc_zones = [
                        z for z in self._discovered_zones
                        if z.ControlMethod == "PercentageControl"
                    ]
                    return await self.async_step_zone_mode()

        except Exception as e:
            _LOGGER.exception("Error in async_step_user: %s", e)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={},
        )

    async def async_step_zone_mode(self, user_input: dict[str, Any] | None = None):
        """Second step: choose how to handle non-ITC zones."""
        errors = {}

        if user_input is not None:
            self._setup_mode = user_input["setup_mode"]
            if self._setup_mode == MODE_NONITC_CLIMATE:
                # If user wants non-ITC as climate, prompt for sensor selections.
                if not self._non_itc_zones:
                    return await self.async_step_finish()
                return await self.async_step_nonitc_sensors()
            else:
                # For default or nonitc_fan, no sensor selection is needed.
                return await self.async_step_finish()

        zone_mode_schema = vol.Schema(
            {
                vol.Required("setup_mode", default=MODE_DEFAULT): vol.In(
                    {
                        MODE_DEFAULT: "Default (all zones as climate)",
                        MODE_NONITC_FAN: "Non-ITC zones as Fans",
                        MODE_NONITC_CLIMATE: "Non-ITC zones as Climate entity (user-selected temperature sensor)",
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="zone_mode",
            data_schema=zone_mode_schema,
            errors=errors,
            description_placeholders={},
        )

    async def async_step_nonitc_sensors(self, user_input: dict[str, Any] | None = None):
        """Prompt user for a temperature sensor for each non-ITC zone with friendlier field labels."""
        errors = {}

        if user_input is not None:
            try:
                for z in self._non_itc_zones:
                    safe_name = z.GroupName.lower().replace(" ", "_").replace("-", "_")
                    key = f"{safe_name}_sensor"
                    if key not in user_input or not user_input[key]:
                        errors["base"] = "missing_sensor"
                        break

                if not errors:
                    for z in self._non_itc_zones:
                        safe_name = z.GroupName.lower().replace(" ", "_").replace("-", "_")
                        key = f"{safe_name}_sensor"
                        self._temp_sensors[z.GroupNumber] = user_input[key]
                    return await self.async_step_finish()

            except Exception as e:
                _LOGGER.exception("Error in nonitc_sensors step: %s", e)
                errors["base"] = "unknown"

        schema_dict = {}
        for z in self._non_itc_zones:
            safe_name = z.GroupName.lower().replace(" ", "_").replace("-", "_")
            key = f"{safe_name}_sensor"
            schema_dict[vol.Required(key)] = selector.selector(
                {
                    "entity": {
                        "domain": ["sensor"],
                        "device_class": ["temperature"],
                        "multiple": False,
                    }
                }
            )

        return self.async_show_form(
            step_id="nonitc_sensors",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        """Final step: create the config entry with all stored data."""
        data = {
            CONF_HOST: self._host,
            "setup_mode": self._setup_mode,
            "nonitc_sensors": self._temp_sensors,
        }
        return self.async_create_entry(
            title=str(self._host),
            data=data
        )
