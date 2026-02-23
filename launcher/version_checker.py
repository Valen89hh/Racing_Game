"""
launcher/version_checker.py - Version checking against remote sources.

Supports two sources:
  1. GitHub Releases API (primary)
  2. Direct version.json URL (secondary, if configured)
"""

import re
import requests

from launcher.config import VERSION_FILE


def parse_version(version_str):
    """Parse a version string like '1.2.3' or 'v1.2.3' into (major, minor, patch)."""
    version_str = version_str.strip().lstrip("v")
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", version_str)
    if not m:
        raise ValueError(f"Invalid version: {version_str!r}")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def version_to_str(version_tuple):
    """Convert (major, minor, patch) back to string."""
    return f"{version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]}"


def read_local_version():
    """Read version from version.txt. Returns '0.0.0' if missing."""
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, FileNotFoundError):
        return "0.0.0"


def write_local_version(version_str):
    """Write version string to version.txt."""
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(version_str.strip() + "\n")


class VersionChecker:
    """Checks for updates from a remote source."""

    def __init__(self, config):
        self.config = config
        self.remote_version = None
        self.download_url = None
        self.error = None

    def check(self):
        """Check for updates. Returns True if an update is available."""
        self.error = None
        self.remote_version = None
        self.download_url = None

        try:
            local = parse_version(read_local_version())
        except ValueError:
            local = (0, 0, 0)

        try:
            if self.config.version_url:
                self._check_version_json(local)
            else:
                self._check_github(local)
        except requests.ConnectionError:
            self.error = "No internet connection"
            return False
        except requests.Timeout:
            self.error = "Connection timed out"
            return False
        except Exception as e:
            self.error = str(e)
            return False

        if self.remote_version and self.download_url:
            try:
                remote = parse_version(self.remote_version)
                return remote > local
            except ValueError:
                self.error = f"Invalid remote version: {self.remote_version}"
                return False

        return False

    def _check_github(self, local_tuple):
        """Check GitHub Releases API for the latest release."""
        resp = requests.get(
            self.config.update_url,
            timeout=self.config.connection_timeout,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        resp.raise_for_status()
        data = resp.json()

        tag = data.get("tag_name", "")
        if not tag:
            self.error = "No tag_name in release"
            return

        self.remote_version = tag.lstrip("v")

        # Find .zip asset
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".zip"):
                self.download_url = asset.get("browser_download_url", "")
                break

        if not self.download_url:
            self.error = "No .zip asset found in release"

    def _check_version_json(self, local_tuple):
        """Check a direct version.json URL."""
        resp = requests.get(
            self.config.version_url,
            timeout=self.config.connection_timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        self.remote_version = data.get("version", "").lstrip("v")
        self.download_url = data.get("download_url", "")

        if not self.remote_version:
            self.error = "No 'version' field in version.json"
        if not self.download_url:
            self.error = "No 'download_url' field in version.json"
