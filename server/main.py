"""Vercel entrypoint (see [tool.vercel] in pyproject.toml). The app lives in retrack_server.app.

Vercel installs dependencies but not this package itself, so src/ is put on the import path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import retrack_server.app  # noqa: E402

app = retrack_server.app.app
