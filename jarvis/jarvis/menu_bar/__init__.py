"""JARVIS macOS Menu Bar app — status indicator and quick controls.

Note: JarvisMenuBarApp and main() require `rumps`.
Import them directly from jarvis.menu_bar.app when rumps is available.
"""

from jarvis.menu_bar.status import JarvisStatus, StatusMonitor

# Lazy imports — these require `rumps` which may not be installed everywhere
def get_app_class():
    from jarvis.menu_bar.app import JarvisMenuBarApp
    return JarvisMenuBarApp


def launch_main():
    from jarvis.menu_bar.app import main
    main()

__all__ = [
    "JarvisStatus",
    "StatusMonitor",
    "get_app_class",
    "launch_main",
]