#!/usr/bin/env python3
"""
Start the HCAI Compliance Engine API server.

Usage:
    python serve.py                         # defaults: 0.0.0.0, port from $PORT or 8000
    python serve.py --host 127.0.0.1 --port 8080
    python serve.py --reload                # development hot-reload
"""

import os

import click
import uvicorn


@click.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host")
@click.option(
    "--port",
    default=lambda: int(os.environ.get("PORT", "8000")),
    show_default=True,
    type=int,
    help="Bind port (defaults to $PORT env var, then 8000)",
)
@click.option("--reload", is_flag=True, default=False, help="Enable hot-reload (development)")
@click.option("--workers", default=1, show_default=True, type=int, help="Number of worker processes")
@click.option("--log-level", default="info", show_default=True,
              type=click.Choice(["debug", "info", "warning", "error"]))
def serve(host: str, port: int, reload: bool, workers: int, log_level: str) -> None:
    """Start the BlueprintIQ HCAI Compliance Engine FastAPI server."""
    click.echo(f"Starting BlueprintIQ on http://{host}:{port}")
    click.echo(f"  Docs:  http://{host}:{port}/docs")
    uvicorn.run(
        "src.api.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=1 if reload else workers,
        log_level=log_level,
    )


if __name__ == "__main__":
    serve()

