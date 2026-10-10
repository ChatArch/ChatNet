"""ChatEnv configuration schemas provided by ChatNet."""

from __future__ import annotations

from chatenv import EnvStore, get_paths
from chatenv.fields import BaseEnvConfig, EnvField


class ChatNetProxyConfig(BaseEnvConfig):
    """One ChatNet namespace for proxy and offline recovery settings."""

    _title = "ChatNet"
    _aliases = ["chatnet", "chatnet-proxy", "proxy"]
    _storage_dir = "ChatNet"

    CHATNET_PROXY_BIND = EnvField("CHATNET_PROXY_BIND", default="127.0.0.1", desc="Forward proxy listen address.")
    CHATNET_PROXY_PORT = EnvField("CHATNET_PROXY_PORT", default="18080", desc="Forward proxy listen port.")
    CHATNET_PROXY_ALLOW_CIDR = EnvField("CHATNET_PROXY_ALLOW_CIDR", default="127.0.0.0/8", desc="Comma-separated client CIDR allowlist.")
    CHATNET_PROXY_USER = EnvField("CHATNET_PROXY_USER", desc="Optional Basic auth username for the forward proxy.")
    CHATNET_PROXY_PASSWORD = EnvField("CHATNET_PROXY_PASSWORD", desc="Optional Basic auth password for the forward proxy.", is_sensitive=True)

    CHATNET_RECOVERY_INTERFACE = EnvField("CHATNET_RECOVERY_INTERFACE", default="", desc="Wi-Fi interface; empty selects the unique kernel Wi-Fi interface.")
    CHATNET_RECOVERY_CONNECTION = EnvField("CHATNET_RECOVERY_CONNECTION", default="", desc="Existing NetworkManager connection name or UUID; no credentials.")
    CHATNET_RECOVERY_RESCUE_PEER = EnvField("CHATNET_RECOVERY_RESCUE_PEER", default="", desc="Management peer IP reachable over physical Ethernet.")
    CHATNET_RECOVERY_PROBE_HOST = EnvField("CHATNET_RECOVERY_PROBE_HOST", default="", desc="Optional extra IP probe; gateway health takes precedence.")
    CHATNET_RECOVERY_COOLDOWN = EnvField("CHATNET_RECOVERY_COOLDOWN", default="300", desc="Minimum seconds between attempts.")
    CHATNET_RECOVERY_MAX_ATTEMPTS = EnvField("CHATNET_RECOVERY_MAX_ATTEMPTS", default="3", desc="Maximum attempts in the sliding window.")
    CHATNET_RECOVERY_WINDOW = EnvField("CHATNET_RECOVERY_WINDOW", default="3600", desc="Recovery budget window in seconds.")
    CHATNET_RECOVERY_MODULE_RELOAD = EnvField("CHATNET_RECOVERY_MODULE_RELOAD", default="false", desc="Enable the guarded module unload/load, device settlement and saved-connection recovery path.")

    @classmethod
    def test(cls) -> None:
        """Validate that the ChatNet proxy config schema is loadable."""

        load_chatnet_proxy_config()
        print(f"Testing {cls._title}...")
        print(f"Config loaded. Bind: {cls.CHATNET_PROXY_BIND.value}:{cls.CHATNET_PROXY_PORT.value}")
        print(f"Allow CIDR: {cls.CHATNET_PROXY_ALLOW_CIDR.value}")
        print(f"Auth user configured: {bool(cls.CHATNET_PROXY_USER.value)}")
        print(f"Auth password configured: {bool(cls.CHATNET_PROXY_PASSWORD.value)}")
        from chatnet.recovery import load_recovery_settings
        load_recovery_settings()
        print("Recovery settings validated; no network actions performed.")


def load_chatnet_proxy_config() -> type[ChatNetProxyConfig]:
    """Load ChatNet proxy config from ChatEnv plus process env overrides."""

    env_values = EnvStore(get_paths().envs_dir).load_active(ChatNetProxyConfig)
    ChatNetProxyConfig.load_from_sources(env_values=env_values)
    return ChatNetProxyConfig


__all__ = ["ChatNetProxyConfig", "load_chatnet_proxy_config"]
