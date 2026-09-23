"""Write the OpenAPI schema to stdout without a running server (used by `make types`)."""

from __future__ import annotations

import json
import sys

from momentum.app import create_app
from momentum.core.settings import Settings


def main() -> None:
    app = create_app(Settings(serve_spa=False, auth_mode="dev", _env_file=None))
    json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
