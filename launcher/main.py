"""
launcher/main.py - Launcher application orchestrator.

Manages the update check/download lifecycle and launches the game.
"""

import os
import subprocess
import sys
import threading

import pygame

from launcher.config import LauncherConfig, GAME_DIR, GAME_EXE
from launcher.ui import LauncherUI, TEXT_GREEN, TEXT_RED, TEXT_CYAN, TEXT_WHITE
from launcher.version_checker import VersionChecker, read_local_version
from launcher.updater import UpdateManager


class LauncherApp:
    """Main launcher application."""

    def __init__(self):
        pygame.init()
        self.config = LauncherConfig()
        self.ui = LauncherUI()
        self.clock = pygame.time.Clock()
        self.running = True

        # Update state
        self._checker = None
        self._updater = None
        self._worker_thread = None
        self._update_available = False
        self._remote_version = None
        self._download_url = None

        # Read local version
        self._refresh_version()

        # Auto-check on launch
        if self.config.check_on_launch:
            self._start_check()

    def _refresh_version(self):
        v = read_local_version()
        self.ui.version_text = f"v{v}"

    def _start_check(self):
        """Start an update check in a background thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self.ui.status_text = "Checking for updates..."
        self.ui.status_color = TEXT_CYAN
        self.ui.btn_update.enabled = False

        self._checker = VersionChecker(self.config)
        self._worker_thread = threading.Thread(target=self._do_check, daemon=True)
        self._worker_thread.start()

    def _do_check(self):
        """Run in background thread: check for updates."""
        has_update = self._checker.check()

        if has_update:
            self._update_available = True
            self._remote_version = self._checker.remote_version
            self._download_url = self._checker.download_url
            local = read_local_version()
            self.ui.status_text = (
                f"Update available: v{local} -> v{self._remote_version}"
            )
            self.ui.status_color = TEXT_GREEN
            self.ui.btn_update.text = "Download Update"
        elif self._checker.error:
            self.ui.status_text = self._checker.error
            self.ui.status_color = TEXT_RED
        else:
            self.ui.status_text = "You're up to date!"
            self.ui.status_color = TEXT_GREEN

        self.ui.btn_update.enabled = True

    def _start_download(self):
        """Start downloading and installing the update."""
        if self._worker_thread and self._worker_thread.is_alive():
            return

        self.ui.btn_update.enabled = False
        self.ui.btn_play.enabled = False
        self.ui.progress = 0.0

        self._updater = UpdateManager(self.config)
        self._worker_thread = threading.Thread(target=self._do_download, daemon=True)
        self._worker_thread.start()

    def _do_download(self):
        """Run in background thread: download and install update."""
        def on_progress(pct, msg):
            self.ui.progress = pct
            self.ui.progress_text = msg
            self.ui.status_text = msg
            self.ui.status_color = TEXT_CYAN

        try:
            self._updater.download_and_install(
                self._download_url,
                self._remote_version,
                progress_callback=on_progress,
            )
            self.ui.status_text = "Update complete! Ready to play."
            self.ui.status_color = TEXT_GREEN
            self._update_available = False
            self.ui.btn_update.text = "Check for Updates"
            self._refresh_version()
        except Exception as e:
            self.ui.status_text = f"Update failed: {e}"
            self.ui.status_color = TEXT_RED

        self.ui.progress = -1.0
        self.ui.btn_play.enabled = True
        self.ui.btn_update.enabled = True

    def _launch_game(self):
        """Launch the game executable (or dev mode script)."""
        if getattr(sys, "frozen", False):
            # Frozen: launch game.exe
            if not os.path.exists(GAME_EXE):
                self.ui.status_text = "game.exe not found!"
                self.ui.status_color = TEXT_RED
                return
            subprocess.Popen([GAME_EXE], cwd=GAME_DIR)
        else:
            # Dev mode: run main.py from project root
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            main_py = os.path.join(project_root, "main.py")
            subprocess.Popen([sys.executable, main_py], cwd=project_root)

        self.running = False

    def run(self):
        """Main loop."""
        while self.running:
            events = self.ui.pump_events()

            for ev in events:
                if ev.type == pygame.QUIT:
                    self.running = False
                    break

                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        self.running = False
                        break

                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    pos = ev.pos
                    if self.ui.btn_play.is_clicked(pos):
                        self._launch_game()
                    elif self.ui.btn_update.is_clicked(pos):
                        if self._update_available:
                            self._start_download()
                        else:
                            self._start_check()

            self.ui.render()
            self.clock.tick(30)

        # Wait for worker thread to finish before quitting
        if self._worker_thread and self._worker_thread.is_alive():
            if self._updater:
                self._updater.cancel()
            self._worker_thread.join(timeout=3)

        pygame.quit()


def main():
    """Entry point for the launcher."""
    LauncherApp().run()


if __name__ == "__main__":
    main()
