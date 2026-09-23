"""ASGI entry point for servers: ``uvicorn momentum.asgi:app``."""

from momentum.app import create_app

app = create_app()
