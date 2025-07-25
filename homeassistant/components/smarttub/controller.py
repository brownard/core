"""Interface to the SmartTub API."""

import asyncio
from datetime import timedelta
import logging
from typing import Any

from aiohttp import client_exceptions
from smarttub import APIError, LoginFailed, SmartTub, Spa
from smarttub.api import Account

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_ERRORS,
    ATTR_LIGHTS,
    ATTR_PUMPS,
    ATTR_REMINDERS,
    ATTR_SENSORS,
    ATTR_STATUS,
    DOMAIN,
    POLLING_TIMEOUT,
    SCAN_INTERVAL,
)
from .helpers import get_spa_name

_LOGGER = logging.getLogger(__name__)

type SmartTubConfigEntry = ConfigEntry[SmartTubController]


class SmartTubController:
    """Interface between Home Assistant and the SmartTub API."""

    coordinator: DataUpdateCoordinator[dict[str, Any]]
    spas: list[Spa]
    _account: Account

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize an interface to SmartTub."""
        self._hass = hass

    async def async_setup_entry(self, entry: SmartTubConfigEntry) -> bool:
        """Perform initial setup.

        Authenticate, query static state, set up polling, and otherwise make
        ready for normal operations .
        """

        try:
            self._account = await self.login(
                entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
            )
        except LoginFailed as ex:
            # credentials were changed or invalidated, we need new ones
            raise ConfigEntryAuthFailed from ex
        except (
            TimeoutError,
            client_exceptions.ClientOSError,
            client_exceptions.ServerDisconnectedError,
            client_exceptions.ContentTypeError,
        ) as err:
            raise ConfigEntryNotReady from err

        self.spas = await self._account.get_spas()

        self.coordinator = DataUpdateCoordinator(
            self._hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self.async_update_data,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )

        await self.coordinator.async_refresh()

        self.async_register_devices(entry)

        return True

    async def async_update_data(self) -> dict[str, Any]:
        """Query the API and return the new state."""

        data = {}
        try:
            async with asyncio.timeout(POLLING_TIMEOUT):
                for spa in self.spas:
                    data[spa.id] = await self._get_spa_data(spa)
        except APIError as err:
            raise UpdateFailed(err) from err

        return data

    async def _get_spa_data(self, spa: Spa) -> dict[str, Any]:
        full_status, reminders, errors = await asyncio.gather(
            spa.get_status_full(),
            spa.get_reminders(),
            spa.get_errors(),
        )
        return {
            ATTR_STATUS: full_status,
            ATTR_PUMPS: {pump.id: pump for pump in full_status.pumps},
            ATTR_LIGHTS: {light.zone: light for light in full_status.lights},
            ATTR_REMINDERS: {reminder.id: reminder for reminder in reminders},
            ATTR_ERRORS: errors,
            ATTR_SENSORS: {sensor.address: sensor for sensor in full_status.sensors},
        }

    @callback
    def async_register_devices(self, entry: SmartTubConfigEntry) -> None:
        """Register devices with the device registry for all spas."""
        device_registry = dr.async_get(self._hass)
        for spa in self.spas:
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                identifiers={(DOMAIN, spa.id)},
                manufacturer=spa.brand,
                name=get_spa_name(spa),
                model=spa.model,
            )

    async def login(self, email: str, password: str) -> Account:
        """Retrieve the account corresponding to the specified email and password."""

        api = SmartTub(async_get_clientsession(self._hass))

        await api.login(email, password)
        return await api.get_account()
