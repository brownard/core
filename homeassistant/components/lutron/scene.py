"""Support for Lutron scenes."""

from __future__ import annotations

from typing import Any

from pylutron import Button, Keypad, Lutron

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import LutronConfigEntry
from .entity import LutronKeypad


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: LutronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lutron scene platform.

    Adds scenes from the Main Repeater associated with the config_entry as
    scene entities.
    """
    entry_data = config_entry.runtime_data

    async_add_entities(
        LutronScene(area_name, keypad, device, entry_data.client)
        for area_name, keypad, device, led in entry_data.scenes
    )


class LutronScene(LutronKeypad, Scene):
    """Representation of a Lutron Scene."""

    _lutron_device: Button

    def __init__(
        self,
        area_name: str,
        keypad: Keypad,
        lutron_device: Button,
        controller: Lutron,
    ) -> None:
        """Initialize the scene/button."""
        super().__init__(area_name, lutron_device, controller, keypad)
        self._attr_name = lutron_device.name

    def activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        self._lutron_device.tap()
