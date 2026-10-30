#!/usr/bin/env python3
"""
TERMIQ Desktop Workspace Window Launcher.

If GTK4 and WebKit are available, opens a dedicated native desktop window.
Otherwise, launches the full workspace interface in the default system browser.
"""

import os
import shutil
import subprocess
import sys

URL = "http://127.0.0.1:8765/workspace/"


def launch_native_window():
    """Attempt to launch as a standalone desktop window using GTK4 + WebKit."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("WebKit", "6.0")
        from gi.repository import Adw, GLib, Gtk, WebKit

        class TermiqApp(Adw.Application):
            def __init__(self):
                super().__init__(application_id="org.termiq.workspace")

            def do_activate(self):
                win = Adw.ApplicationWindow(application=self, title="TERMIQ — Linux Desktop Copilot")
                win.set_default_size(1180, 780)

                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                header = Adw.HeaderBar()
                box.append(header)

                webview = WebKit.WebView()
                webview.load_uri(URL)
                webview.set_vexpand(True)
                webview.set_hexpand(True)
                box.append(webview)

                win.set_content(box)
                win.present()

        app = TermiqApp()
        return app.run([])
    except Exception as exc:
        # Fallback to browser
        return launch_browser()


def launch_browser():
    """Launch the workspace in the default Linux browser."""
    gio_bin = shutil.which("gio")
    if gio_bin:
        subprocess.Popen([gio_bin, "open", URL])
        return 0
    xdg_bin = shutil.which("xdg-open")
    if xdg_bin:
        subprocess.Popen([xdg_bin, URL])
        return 0
    import webbrowser
    webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    sys.exit(launch_native_window())

