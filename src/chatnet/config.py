"""ChatEnv configuration schemas provided by ChatNet."""

from __future__ import annotations

from chatenv import EnvStore, get_paths
from chatenv.fields import BaseEnvConfig, EnvField


class ChatNetProxyConfig(BaseEnvConfig):
    """ChatNet forward proxy environment variables."""

    _title = "ChatNet Proxy"
    _aliases = ["chatnet", "chatnet-proxy", "proxy"]
    _storage_dir = "ChatNet"

    CHATNET_PROXY_BIND = EnvField("CHATNET_PROXY_BIND", default="127.0.0.1", desc="Forward proxy listen address.")
    CHATNET_PROXY_PORT = EnvField("CHATNET_PROXY_PORT", default="18080", desc="Forward proxy listen port.")
    CHATNET_PROXY_ALLOW_CIDR = EnvField("CHATNET_PROXY_ALLOW_CIDR", default="127.0.0.0/8", desc="Comma-separated client CIDR allowlist.")
    CHATNET_PROXY_USER = EnvField("CHATNET_PROXY_USER", desc="Optional Basic auth username for the forward proxy.")
    CHATNET_PROXY_PASSWORD = EnvField("CHATNET_PROXY_PASSWORD", desc="Optional Basic auth password for the forward proxy.", is_sensitive=True)

    @classmethod
    def test(cls) -> None:
        """Validate that the ChatNet proxy config schema is loadable."""

        load_chatnet_proxy_config()
        print(f"Testing {cls._title}...")
        print(f"Config loaded. Bind: {cls.CHATNET_PROXY_BIND.value}:{cls.CHATNET_PROXY_PORT.value}")
        print(f"Allow CIDR: {cls.CHATNET_PROXY_ALLOW_CIDR.value}")
        print(f"Auth user configured: {bool(cls.CHATNET_PROXY_USER.value)}")
        print(f"Auth password configured: {bool(cls.CHATNET_PROXY_PASSWORD.value)}")


def load_chatnet_proxy_config() -> type[ChatNetProxyConfig]:
    """Load ChatNet proxy config from ChatEnv plus process env overrides."""

    env_values = EnvStore(get_paths().envs_dir).load_active(ChatNetProxyConfig)
    ChatNetProxyConfig.load_from_sources(env_values=env_values)
    return ChatNetProxyConfig


__all__ = ["ChatNetProxyConfig", "load_chatnet_proxy_config"]
