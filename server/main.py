"""Vercel entrypoint (see [tool.vercel] in pyproject.toml). The app lives in retrack_server.app."""

import retrack_server.app

app = retrack_server.app.app
