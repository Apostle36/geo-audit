"""Shared, lazy Playwright launch policy for reports and browser observations."""
import os
import shutil
import sys

SYSTEM_BROWSERS = ('/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser')


def launch_chromium(playwright):
    from playwright.sync_api import Error
    options = {'args': ['--disable-dev-shm-usage']}
    explicit = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH')
    if explicit:
        return playwright.chromium.launch(executable_path=explicit, **options)
    try:
        return playwright.chromium.launch(**options)
    except Error as exc:
        if "Executable doesn't exist" not in str(exc):
            raise
        for candidate in SYSTEM_BROWSERS:
            if shutil.which(candidate):
                print(f"Playwright's Chromium is not installed; using {candidate}", file=sys.stderr)
                return playwright.chromium.launch(executable_path=candidate, **options)
        raise
