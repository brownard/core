"""Support for Switchbot devices."""

import logging

import switchbot

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_MAC,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SENSOR_TYPE,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_ENCRYPTION_KEY,
    CONF_KEY_ID,
    CONF_RETRY_COUNT,
    CONNECTABLE_SUPPORTED_MODEL_TYPES,
    DEFAULT_RETRY_COUNT,
    DOMAIN,
    ENCRYPTED_MODELS,
    HASS_SENSOR_TYPE_TO_SWITCHBOT_MODEL,
    SupportedModels,
)
from .coordinator import SwitchbotConfigEntry, SwitchbotDataUpdateCoordinator

PLATFORMS_BY_TYPE = {
    SupportedModels.BULB.value: [Platform.SENSOR, Platform.LIGHT],
    SupportedModels.LIGHT_STRIP.value: [Platform.SENSOR, Platform.LIGHT],
    SupportedModels.CEILING_LIGHT.value: [Platform.SENSOR, Platform.LIGHT],
    SupportedModels.BOT.value: [Platform.SWITCH, Platform.SENSOR],
    SupportedModels.PLUG.value: [Platform.SWITCH, Platform.SENSOR],
    SupportedModels.CURTAIN.value: [
        Platform.COVER,
        Platform.BINARY_SENSOR,
        Platform.SENSOR,
    ],
    SupportedModels.HYGROMETER.value: [Platform.SENSOR],
    SupportedModels.HYGROMETER_CO2.value: [Platform.SENSOR],
    SupportedModels.CONTACT.value: [Platform.BINARY_SENSOR, Platform.SENSOR],
    SupportedModels.MOTION.value: [Platform.BINARY_SENSOR, Platform.SENSOR],
    SupportedModels.HUMIDIFIER.value: [Platform.HUMIDIFIER, Platform.SENSOR],
    SupportedModels.LOCK.value: [
        Platform.BINARY_SENSOR,
        Platform.LOCK,
        Platform.SENSOR,
    ],
    SupportedModels.LOCK_PRO.value: [
        Platform.BINARY_SENSOR,
        Platform.LOCK,
        Platform.SENSOR,
    ],
    SupportedModels.BLIND_TILT.value: [
        Platform.COVER,
        Platform.BINARY_SENSOR,
        Platform.SENSOR,
    ],
    SupportedModels.HUB2.value: [Platform.SENSOR],
    SupportedModels.RELAY_SWITCH_1PM.value: [Platform.SWITCH, Platform.SENSOR],
    SupportedModels.RELAY_SWITCH_1.value: [Platform.SWITCH],
    SupportedModels.LEAK.value: [Platform.BINARY_SENSOR, Platform.SENSOR],
    SupportedModels.REMOTE.value: [Platform.SENSOR],
    SupportedModels.ROLLER_SHADE.value: [
        Platform.COVER,
        Platform.BINARY_SENSOR,
        Platform.SENSOR,
    ],
    SupportedModels.HUBMINI_MATTER.value: [Platform.SENSOR],
    SupportedModels.CIRCULATOR_FAN.value: [Platform.FAN, Platform.SENSOR],
    SupportedModels.K20_VACUUM.value: [Platform.VACUUM, Platform.SENSOR],
    SupportedModels.S10_VACUUM.value: [Platform.VACUUM, Platform.SENSOR],
    SupportedModels.K10_VACUUM.value: [Platform.VACUUM, Platform.SENSOR],
    SupportedModels.K10_PRO_VACUUM.value: [Platform.VACUUM, Platform.SENSOR],
    SupportedModels.K10_PRO_COMBO_VACUUM.value: [Platform.VACUUM, Platform.SENSOR],
    SupportedModels.HUB3.value: [Platform.SENSOR, Platform.BINARY_SENSOR],
    SupportedModels.LOCK_LITE.value: [
        Platform.BINARY_SENSOR,
        Platform.LOCK,
        Platform.SENSOR,
    ],
    SupportedModels.LOCK_ULTRA.value: [
        Platform.BINARY_SENSOR,
        Platform.LOCK,
        Platform.SENSOR,
    ],
    SupportedModels.AIR_PURIFIER.value: [Platform.FAN, Platform.SENSOR],
    SupportedModels.AIR_PURIFIER_TABLE.value: [Platform.FAN, Platform.SENSOR],
    SupportedModels.EVAPORATIVE_HUMIDIFIER: [Platform.HUMIDIFIER, Platform.SENSOR],
    SupportedModels.FLOOR_LAMP.value: [Platform.LIGHT, Platform.SENSOR],
    SupportedModels.STRIP_LIGHT_3.value: [Platform.LIGHT, Platform.SENSOR],
}
CLASS_BY_DEVICE = {
    SupportedModels.CEILING_LIGHT.value: switchbot.SwitchbotCeilingLight,
    SupportedModels.CURTAIN.value: switchbot.SwitchbotCurtain,
    SupportedModels.BOT.value: switchbot.Switchbot,
    SupportedModels.PLUG.value: switchbot.SwitchbotPlugMini,
    SupportedModels.BULB.value: switchbot.SwitchbotBulb,
    SupportedModels.LIGHT_STRIP.value: switchbot.SwitchbotLightStrip,
    SupportedModels.HUMIDIFIER.value: switchbot.SwitchbotHumidifier,
    SupportedModels.LOCK.value: switchbot.SwitchbotLock,
    SupportedModels.LOCK_PRO.value: switchbot.SwitchbotLock,
    SupportedModels.BLIND_TILT.value: switchbot.SwitchbotBlindTilt,
    SupportedModels.RELAY_SWITCH_1PM.value: switchbot.SwitchbotRelaySwitch,
    SupportedModels.RELAY_SWITCH_1.value: switchbot.SwitchbotRelaySwitch,
    SupportedModels.ROLLER_SHADE.value: switchbot.SwitchbotRollerShade,
    SupportedModels.CIRCULATOR_FAN.value: switchbot.SwitchbotFan,
    SupportedModels.K20_VACUUM.value: switchbot.SwitchbotVacuum,
    SupportedModels.S10_VACUUM.value: switchbot.SwitchbotVacuum,
    SupportedModels.K10_VACUUM.value: switchbot.SwitchbotVacuum,
    SupportedModels.K10_PRO_VACUUM.value: switchbot.SwitchbotVacuum,
    SupportedModels.K10_PRO_COMBO_VACUUM.value: switchbot.SwitchbotVacuum,
    SupportedModels.LOCK_LITE.value: switchbot.SwitchbotLock,
    SupportedModels.LOCK_ULTRA.value: switchbot.SwitchbotLock,
    SupportedModels.AIR_PURIFIER.value: switchbot.SwitchbotAirPurifier,
    SupportedModels.AIR_PURIFIER_TABLE.value: switchbot.SwitchbotAirPurifier,
    SupportedModels.EVAPORATIVE_HUMIDIFIER: switchbot.SwitchbotEvaporativeHumidifier,
    SupportedModels.FLOOR_LAMP.value: switchbot.SwitchbotStripLight3,
    SupportedModels.STRIP_LIGHT_3.value: switchbot.SwitchbotStripLight3,
}


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: SwitchbotConfigEntry) -> bool:
    """Set up Switchbot from a config entry."""
    assert entry.unique_id is not None
    if CONF_ADDRESS not in entry.data and CONF_MAC in entry.data:
        # Bleak uses addresses not mac addresses which are actually
        # UUIDs on some platforms (MacOS).
        mac = entry.data[CONF_MAC]
        if "-" not in mac:
            mac = dr.format_mac(mac)
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ADDRESS: mac},
        )

    if not entry.options:
        hass.config_entries.async_update_entry(
            entry,
            options={CONF_RETRY_COUNT: DEFAULT_RETRY_COUNT},
        )

    sensor_type: str = entry.data[CONF_SENSOR_TYPE]
    switchbot_model = HASS_SENSOR_TYPE_TO_SWITCHBOT_MODEL[sensor_type]
    # connectable means we can make connections to the device
    connectable = switchbot_model in CONNECTABLE_SUPPORTED_MODEL_TYPES
    address: str = entry.data[CONF_ADDRESS]

    await switchbot.close_stale_connections_by_address(address)

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable
    )
    if not ble_device:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found_error",
            translation_placeholders={"sensor_type": sensor_type, "address": address},
        )

    cls = CLASS_BY_DEVICE.get(sensor_type, switchbot.SwitchbotDevice)
    if switchbot_model in ENCRYPTED_MODELS:
        try:
            device = cls(
                device=ble_device,
                key_id=entry.data.get(CONF_KEY_ID),
                encryption_key=entry.data.get(CONF_ENCRYPTION_KEY),
                retry_count=entry.options[CONF_RETRY_COUNT],
                model=switchbot_model,
            )
        except ValueError as error:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="value_error",
                translation_placeholders={"error": str(error)},
            ) from error
    else:
        device = cls(
            device=ble_device,
            password=entry.data.get(CONF_PASSWORD),
            retry_count=entry.options[CONF_RETRY_COUNT],
        )

    coordinator = entry.runtime_data = SwitchbotDataUpdateCoordinator(
        hass,
        _LOGGER,
        ble_device,
        device,
        entry.unique_id,
        entry.data.get(CONF_NAME, entry.title),
        connectable,
        switchbot_model,
    )
    entry.async_on_unload(coordinator.async_start())
    if not await coordinator.async_wait_ready():
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="advertising_state_error",
            translation_placeholders={"address": address},
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(
        entry, PLATFORMS_BY_TYPE[sensor_type]
    )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    sensor_type = entry.data[CONF_SENSOR_TYPE]
    return await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS_BY_TYPE[sensor_type]
    )
