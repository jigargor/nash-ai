"""MCP (Model Context Protocol) server for external repository review.

Exposes the :class:`ReviewEngine` through a structured tool surface so
any MCP-capable client (Claude Desktop, Cursor, custom agents) can
drive repository reviews while handling reasoning themselves.

Two transports are supported:

* **stdio** — default when invoking ``python -m app.mcp`` or
  ``python -m app.mcp.server`` from a client configuration,
* **streamable-http** — enable with ``--transport http`` for browser or
  multi-tenant deployments.
"""

from __future__ import annotations

from app.mcp.server import build_mcp_app

__all__ = ["build_mcp_app"]
