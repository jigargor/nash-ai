"""Reusable repository review library.

This package contains the pure-Python engine used by both the FastAPI/ARQ
orchestrator and the standalone MCP server. The core has no dependency on
the database, queue, or web layer so it can be consumed from any process.
"""
