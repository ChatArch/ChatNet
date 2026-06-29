"""ChatArch generic network helper package."""

from chatnet.forward_proxy import ForwardProxyConfig, make_forward_proxy_server, serve_forward_proxy
from chatnet.forward_proxy_check import ForwardProxyCheckResult, check_forward_proxy
from chatnet.forward_proxy_service import ForwardProxyServiceConfig, install_systemd_user_unit, render_systemd_user_unit
from chatnet.link_check import LinkCheckResult, ServiceCheckResult
from chatnet.scanner import check_port, ping_host, ping_scan, port_scan
from chatnet.service_urls import append_token, ensure_path

__all__ = [
    "__version__",
    "append_token",
    "check_forward_proxy",
    "check_port",
    "ensure_path",
    "ForwardProxyConfig",
    "ForwardProxyCheckResult",
    "ForwardProxyServiceConfig",
    "install_systemd_user_unit",
    "LinkCheckResult",
    "make_forward_proxy_server",
    "ping_host",
    "ping_scan",
    "port_scan",
    "render_systemd_user_unit",
    "serve_forward_proxy",
    "ServiceCheckResult",
]

__version__ = "0.2.0"
