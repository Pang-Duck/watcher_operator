from __future__ import annotations

import logging
import os

import kopf

from watcher_operator import controller  # noqa: F401 - importing registers handlers


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    kopf.run(clusterwide=True, liveness_endpoint=os.getenv("LIVENESS_ENDPOINT", "http://0.0.0.0:8080/healthz"))


if __name__ == "__main__":
    main()
