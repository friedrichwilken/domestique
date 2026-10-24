"""Run the web console: ``python -m domestique.web``.

Binds to ``DOMESTIQUE_WEB_HOST`` (default ``127.0.0.1``) and
``DOMESTIQUE_WEB_PORT`` (default ``8000``). The container sets the host to
``0.0.0.0`` inside its own network namespace; compose publishes the port on
the loopback interface only.
"""

from __future__ import annotations

import os

import uvicorn

from domestique.web.app import create_app, settings_from_env

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def main() -> None:
    host = os.environ.get("DOMESTIQUE_WEB_HOST", DEFAULT_HOST)
    port = int(os.environ.get("DOMESTIQUE_WEB_PORT", str(DEFAULT_PORT)))
    uvicorn.run(create_app(settings_from_env()), host=host, port=port)


if __name__ == "__main__":
    main()
