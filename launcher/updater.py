"""
launcher/updater.py - Download, extract, and install updates with rollback.
"""

import os
import shutil
import tempfile
import zipfile

import requests

from launcher.config import GAME_DIR, TEMP_DIR, BACKUP_DIR
from launcher.version_checker import write_local_version


class UpdateManager:
    """Downloads and installs game updates with automatic rollback on failure."""

    def __init__(self, config):
        self.config = config
        self._cancelled = False
        self._zip_path = None

    def cancel(self):
        """Request cancellation of the current download."""
        self._cancelled = True

    def download_and_install(self, url, new_version, progress_callback=None):
        """Download a .zip update and replace the game/ directory.

        Args:
            url: URL to the .zip file.
            new_version: version string to write after successful install.
            progress_callback: callable(progress_float, status_str).
                progress_float is 0.0 to 1.0.

        Raises:
            Exception on failure (rollback is attempted automatically).
        """
        self._cancelled = False
        self._zip_path = None

        def report(pct, msg):
            if progress_callback:
                progress_callback(pct, msg)

        try:
            # Step 1: Download .zip (0% - 55%)
            report(0.0, "Downloading update...")
            self._zip_path = self._download(url, report)

            if self._cancelled:
                report(0.0, "Update cancelled")
                return

            # Step 2: Verify zip (55% - 60%)
            report(0.55, "Verifying download...")
            self._verify_zip(self._zip_path)

            # Step 3: Extract to temp (60% - 75%)
            report(0.60, "Extracting files...")
            self._extract(self._zip_path)

            # Step 4: Backup current game/ (75% - 80%)
            report(0.75, "Backing up current version...")
            self._backup()

            # Step 5: Swap in new files (80% - 90%)
            report(0.80, "Installing update...")
            self._swap()

            # Step 5b: Preserve user data from backup
            report(0.85, "Restoring user tracks...")
            self._restore_user_data()

            # Step 6: Write version (90% - 95%)
            report(0.90, "Updating version info...")
            write_local_version(new_version)

            # Step 7: Cleanup backup (95% - 100%)
            report(0.95, "Cleaning up...")
            self._cleanup_backup()

            report(1.0, "Update complete!")

        except Exception as e:
            # Rollback: restore backup if it exists
            self._rollback()
            raise RuntimeError(f"Update failed: {e}") from e

        finally:
            # Always clean up temp files
            self._cleanup_temp()

    def _download(self, url, report):
        """Download the zip file with streaming and progress updates."""
        resp = requests.get(
            url,
            stream=True,
            timeout=(self.config.connection_timeout, self.config.download_timeout),
        )
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="game_update_")
        try:
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if self._cancelled:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = min(downloaded / total, 1.0) * 0.55
                        size_mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        report(pct, f"Downloading... {size_mb:.1f}/{total_mb:.1f} MB")
        except Exception:
            # Clean up partial download
            try:
                os.unlink(zip_path)
            except OSError:
                pass
            raise

        return zip_path

    def _verify_zip(self, zip_path):
        """Verify that the downloaded file is a valid zip."""
        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Downloaded file is not a valid zip archive")
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise ValueError(f"Corrupted file in zip: {bad}")

    def _extract(self, zip_path):
        """Extract zip contents to temp directory."""
        # Clean any previous temp
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(TEMP_DIR)

        # Handle zip with a single subdirectory (common in GitHub releases)
        entries = os.listdir(TEMP_DIR)
        if len(entries) == 1:
            single = os.path.join(TEMP_DIR, entries[0])
            if os.path.isdir(single):
                # Move contents up one level
                for item in os.listdir(single):
                    src = os.path.join(single, item)
                    dst = os.path.join(TEMP_DIR, item)
                    shutil.move(src, dst)
                os.rmdir(single)

    def _backup(self):
        """Rename current game/ to backup."""
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR)
        if os.path.exists(GAME_DIR):
            os.rename(GAME_DIR, BACKUP_DIR)

    def _swap(self):
        """Move extracted temp to game/."""
        os.rename(TEMP_DIR, GAME_DIR)

    def _restore_user_data(self):
        """Copy user-created tracks from backup into the new installation."""
        backup_tracks = os.path.join(BACKUP_DIR, "tracks")
        new_tracks = os.path.join(GAME_DIR, "tracks")
        if not os.path.exists(backup_tracks):
            return
        os.makedirs(new_tracks, exist_ok=True)
        for fname in os.listdir(backup_tracks):
            src = os.path.join(backup_tracks, fname)
            dst = os.path.join(new_tracks, fname)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)

    def _cleanup_backup(self):
        """Remove backup directory after successful update."""
        if os.path.exists(BACKUP_DIR):
            shutil.rmtree(BACKUP_DIR, ignore_errors=True)

    def _rollback(self):
        """Attempt to restore game/ from backup."""
        try:
            if os.path.exists(BACKUP_DIR):
                if os.path.exists(GAME_DIR):
                    shutil.rmtree(GAME_DIR, ignore_errors=True)
                os.rename(BACKUP_DIR, GAME_DIR)
                print("[updater] Rollback successful")
        except Exception as e:
            print(f"[updater] WARNING: Rollback failed: {e}")

    def _cleanup_temp(self):
        """Remove temporary files."""
        if self._zip_path and os.path.exists(self._zip_path):
            try:
                os.unlink(self._zip_path)
            except OSError:
                pass
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
