from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _env_positive_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class AccountLockoutConfig:
    enabled: bool
    max_failed_attempts: int
    lockout_duration_minutes: int
    audit_enabled: bool

    @property
    def lockout_duration_seconds(self) -> int:
        return self.lockout_duration_minutes * 60


def load_account_lockout_config() -> AccountLockoutConfig:
    cooldown_seconds = _env_positive_int("LOCKOUT_COOLDOWN_SECONDS", 900)
    default_minutes = max(1, cooldown_seconds // 60)
    max_attempts = _env_positive_int(
        "MAX_FAILED_LOGIN_ATTEMPTS",
        _env_positive_int("LOCKOUT_FAILED_ATTEMPTS", 5),
    )
    lockout_minutes = _env_positive_int(
        "LOCKOUT_DURATION_MINUTES",
        default_minutes,
    )

    return AccountLockoutConfig(
        enabled=_env_bool("ACCOUNT_LOCKOUT_ENABLED", True),
        max_failed_attempts=max_attempts,
        lockout_duration_minutes=lockout_minutes,
        audit_enabled=_env_bool("ENABLE_SECURITY_AUDIT", True),
    )
