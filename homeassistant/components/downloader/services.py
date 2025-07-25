"""Support for functionality to download files."""

from __future__ import annotations

from http import HTTPStatus
import os
import re
import threading

import requests
import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import raise_if_invalid_filename, raise_if_invalid_path

from .const import (
    _LOGGER,
    ATTR_FILENAME,
    ATTR_OVERWRITE,
    ATTR_SUBDIR,
    ATTR_URL,
    CONF_DOWNLOAD_DIR,
    DOMAIN,
    DOWNLOAD_COMPLETED_EVENT,
    DOWNLOAD_FAILED_EVENT,
    SERVICE_DOWNLOAD_FILE,
)


def download_file(service: ServiceCall) -> None:
    """Start thread to download file specified in the URL."""

    entry = service.hass.config_entries.async_loaded_entries(DOMAIN)[0]
    download_path = entry.data[CONF_DOWNLOAD_DIR]

    def do_download() -> None:
        """Download the file."""
        try:
            url = service.data[ATTR_URL]

            subdir = service.data.get(ATTR_SUBDIR)

            filename = service.data.get(ATTR_FILENAME)

            overwrite = service.data.get(ATTR_OVERWRITE)

            if subdir:
                # Check the path
                raise_if_invalid_path(subdir)

            final_path = None

            req = requests.get(url, stream=True, timeout=10)

            if req.status_code != HTTPStatus.OK:
                _LOGGER.warning(
                    "Downloading '%s' failed, status_code=%d", url, req.status_code
                )
                service.hass.bus.fire(
                    f"{DOMAIN}_{DOWNLOAD_FAILED_EVENT}",
                    {"url": url, "filename": filename},
                )

            else:
                if filename is None and "content-disposition" in req.headers:
                    if match := re.search(
                        r"filename=(\S+)", req.headers["content-disposition"]
                    ):
                        filename = match.group(1).strip("'\" ")

                if not filename:
                    filename = os.path.basename(url).strip()

                if not filename:
                    filename = "ha_download"

                # Check the filename
                raise_if_invalid_filename(filename)

                # Do we want to download to subdir, create if needed
                if subdir:
                    subdir_path = os.path.join(download_path, subdir)

                    # Ensure subdir exist
                    os.makedirs(subdir_path, exist_ok=True)

                    final_path = os.path.join(subdir_path, filename)

                else:
                    final_path = os.path.join(download_path, filename)

                path, ext = os.path.splitext(final_path)

                # If file exist append a number.
                # We test filename, filename_2..
                if not overwrite:
                    tries = 1
                    final_path = path + ext
                    while os.path.isfile(final_path):
                        tries += 1

                        final_path = f"{path}_{tries}.{ext}"

                _LOGGER.debug("%s -> %s", url, final_path)

                with open(final_path, "wb") as fil:
                    fil.writelines(req.iter_content(1024))

                _LOGGER.debug("Downloading of %s done", url)
                service.hass.bus.fire(
                    f"{DOMAIN}_{DOWNLOAD_COMPLETED_EVENT}",
                    {"url": url, "filename": filename},
                )

        except requests.exceptions.ConnectionError:
            _LOGGER.exception("ConnectionError occurred for %s", url)
            service.hass.bus.fire(
                f"{DOMAIN}_{DOWNLOAD_FAILED_EVENT}",
                {"url": url, "filename": filename},
            )

            # Remove file if we started downloading but failed
            if final_path and os.path.isfile(final_path):
                os.remove(final_path)
        except ValueError:
            _LOGGER.exception("Invalid value")
            service.hass.bus.fire(
                f"{DOMAIN}_{DOWNLOAD_FAILED_EVENT}",
                {"url": url, "filename": filename},
            )

            # Remove file if we started downloading but failed
            if final_path and os.path.isfile(final_path):
                os.remove(final_path)

    threading.Thread(target=do_download).start()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services for the downloader component."""
    async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_DOWNLOAD_FILE,
        download_file,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_FILENAME): cv.string,
                vol.Optional(ATTR_SUBDIR): cv.string,
                vol.Required(ATTR_URL): cv.url,
                vol.Optional(ATTR_OVERWRITE, default=False): cv.boolean,
            }
        ),
    )
