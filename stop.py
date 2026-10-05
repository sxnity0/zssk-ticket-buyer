"""Stop only the helper's exact Python command, leaving Chromium cleanup to it."""
import os
import signal
from pathlib import Path
for process in Path('/proc').glob('[0-9]*'):
    try:
        args = (process / 'cmdline').read_bytes().split(b'\0')
        if args[:2] == [b'/opt/zssk-venv/bin/python', b'mobile.py']:
            os.kill(int(process.name), signal.SIGTERM)
    except (OSError, ValueError):
        pass
