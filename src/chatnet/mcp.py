"""MCP adapters for ChatNet scanning helpers."""

from __future__ import annotations

from typing import Any, List

try:
    from fastmcp import FastMCP  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional runtime
    FastMCP = None

from chatnet.scanner import ping_scan, port_scan


def network_ping_scan(network_segment: str, concurrency: int = 50) -> List[str]:
    """Scan a network segment for active hosts using ICMP ping."""

    return ping_scan(network_segment, concurrency=concurrency)


def network_port_scan(hosts: List[str], port: int = 22, concurrency: int = 50) -> List[str]:
    """Scan a list of hosts for a specific open port."""

    return port_scan(hosts, port, concurrency=concurrency)


def register(mcp: Any):
    """Register ChatNet tools with a FastMCP server."""

    mcp.tool(name="network_ping_scan", tags=["network", "read"])(network_ping_scan)
    mcp.tool(name="network_port_scan", tags=["network", "read"])(network_port_scan)
