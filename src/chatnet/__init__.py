"""ChatArch generic network helper package."""

from chatnet.link_check import LinkCheckResult, ServiceCheckResult
from chatnet.scanner import check_port, ping_host, ping_scan, port_scan
from chatnet.service_urls import append_token, ensure_path

__all__ = [
    "__version__",
    "append_token",
    "check_port",
    "ensure_path",
    "LinkCheckResult",
    "ping_host",
    "ping_scan",
    "port_scan",
    "ServiceCheckResult",
]

__version__ = "0.2.0.dev0"
