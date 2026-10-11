"""
Shared path helpers.

APP_DIR points at the folder containing the running app. Works in both
source-code and packaged (.exe) form.

When running as a .py file, APP_DIR is the folder of the top-level script.
When running as a .exe (PyInstaller), sys.frozen is True and sys.executable
is the path to the .exe, so APP_DIR points next to the .exe — which is
where config.ini and any external data files should live.
"""

import os
import sys


def get_app_dir():
    """Return the folder where the app is running from."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # When running from source, __file__ is this file — go up one level to
    # reach the folder that contains the entry-point script.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR = get_app_dir()