"""The keenetic_ndms2 component."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    CONF_CONSIDER_HOME,
    CONF_INCLUDE_ARP,
    CONF_INCLUDE_ASSOCIATED,
    CONF_INTERFACES,
    CONF_TRY_HOTSPOT,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_INTERFACE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .router import KeeneticConfigEntry, KeeneticRouter

PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: KeeneticConfigEntry) -> bool:
    """Set up the component."""
    hass.data.setdefault(DOMAIN, {})
    async_add_defaults(hass, entry)

    router = KeeneticRouter(hass, entry)
    await router.async_setup()

    entry.runtime_data = router

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, config_entry: KeeneticConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )

    router = config_entry.runtime_data
    await router.async_teardown()

    new_tracked_interfaces: set[str] = set(config_entry.options[CONF_INTERFACES])

    if router.tracked_interfaces - new_tracked_interfaces:
        _LOGGER.debug(
            "Cleaning device_tracker entities since some interfaces are now untracked:"
        )
        ent_reg = er.async_get(hass)
        dev_reg = dr.async_get(hass)
        # We keep devices currently connected to new_tracked_interfaces
        keep_devices: set[str] = {
            mac
            for mac, device in router.last_devices.items()
            if device.interface in new_tracked_interfaces
        }
        for entity_entry in ent_reg.entities.get_entries_for_config_entry_id(
            config_entry.entry_id
        ):
            if entity_entry.domain == Platform.DEVICE_TRACKER:
                mac = entity_entry.unique_id.partition("_")[0]
                if mac not in keep_devices:
                    _LOGGER.debug("Removing entity %s", entity_entry.entity_id)

                    ent_reg.async_remove(entity_entry.entity_id)
                    if entity_entry.device_id:
                        dev_reg.async_update_device(
                            entity_entry.device_id,
                            remove_config_entry_id=config_entry.entry_id,
                        )

        _LOGGER.debug("Finished cleaning device_tracker entities")

    return unload_ok


def async_add_defaults(hass: HomeAssistant, entry: KeeneticConfigEntry):
    """Populate default options."""
    host: str = entry.data[CONF_HOST]
    imported_options: dict = hass.data[DOMAIN].get(f"imported_options_{host}", {})
    options = {
        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
        CONF_CONSIDER_HOME: DEFAULT_CONSIDER_HOME,
        CONF_INTERFACES: [DEFAULT_INTERFACE],
        CONF_TRY_HOTSPOT: True,
        CONF_INCLUDE_ARP: True,
        CONF_INCLUDE_ASSOCIATED: True,
        **imported_options,
        **entry.options,
    }

    if options.keys() - entry.options.keys():
        hass.config_entries.async_update_entry(entry, options=options)
