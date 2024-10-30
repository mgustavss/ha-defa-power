"""Define coordinators for CloudCharge API."""

import asyncio
from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloudcharge_api.client import CloudChargeAPIClient
from .cloudcharge_api.exceptions import CloudChargeAPIError, CloudChargeAuthError

CONF_TOKEN = "token"
CONF_USER_ID = "userId"

_LOGGER = logging.getLogger(__name__)


class CloudChargeChargersCoordinator(DataUpdateCoordinator):
    """CloudCharge chargers coordinator."""

    def __init__(self, hass, client: CloudChargeAPIClient):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="CloudCharge chargers",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(minutes=60),
            # Set always_update to `False` if the data returned from the
            # api can be compared via `__eq__` to avoid duplicate updates
            # being dispatched to listeners
            always_update=True,
        )
        self.client = client

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        # try:
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        async with asyncio.timeout(10):
            # Grab active context variables to limit data required to be fetched from API
            # Note: using context is not required if there is no need or ability to limit
            # data retrieved from API.
            try:
                chargers_data = await self.client.async_get_private_chargers()
            except CloudChargeAuthError as err:
                raise ConfigEntryAuthFailed from err
            except CloudChargeAPIError as err:
                raise UpdateFailed(f"Error communicating with API: {err}") from err

            chargers = {}
            connectors = {}

            for charger_data in chargers_data:
                charger = charger_data["data"]
                chargers[charger["id"]] = charger
                for connector in charger["aliasMap"].values():
                    connector["chargerId"] = charger["id"]
                    connectors[connector["id"]] = connector

            return {"chargers": chargers, "connectors": connectors}


class CloudChargeOperationalDataCoordinator(DataUpdateCoordinator):
    """CloudCharge operational data coordinator."""

    def __init__(self, connector_id: str, hass, client: CloudChargeAPIClient):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="CloudCharge operational data",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=60),
            # Set always_update to `False` if the data returned from the
            # api can be compared via `__eq__` to avoid duplicate updates
            # being dispatched to listeners
            always_update=True,
        )
        self.connector_id = connector_id
        self.client = client
        self.is_charging = False

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        # try:
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        async with asyncio.timeout(10):
            # Grab active context variables to limit data required to be fetched from API
            # Note: using context is not required if there is no need or ability to limit
            # data retrieved from API.
            try:
                data = await self.client.async_get_operational_data(self.connector_id)
            except CloudChargeAuthError as err:
                raise ConfigEntryAuthFailed from err
            except CloudChargeAPIError as err:
                raise UpdateFailed(f"Error communicating with API: {err}") from err

            charging_state = data.get("ocpp", {}).get("chargingState")

            if charging_state:
                # Update every 10 seconds while charging, otherwise every minute
                if self.is_charging and charging_state != "Charging":
                    self.is_charging = False
                    self.update_interval = timedelta(seconds=60)
                elif not self.is_charging and charging_state == "Charging":
                    self.is_charging = True
                    self.update_interval = timedelta(seconds=10)
                    await self.client.async_start_live_consumption(self.connector_id)
            return data
