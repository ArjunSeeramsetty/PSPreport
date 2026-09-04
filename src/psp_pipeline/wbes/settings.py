"""Feature-gated WBES settings, independent of public PSP ``AppSettings``."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WbesSettings:
    """Runtime configuration for the isolated WBES schedule pipeline."""

    enabled: bool
    allow_live_network: bool
    allow_five_minute: bool
    write_timescale: bool
    project_root: Path
    catalog_path: Path
    raw_dir: Path
    drop_dir: Path
    sqlite_path: Path
    username: str
    password: str
    session_cookie: str
    user_agent: str
    postgres_dsn: str
    block_count: int
    block_minutes: int
    http_timeout_seconds: float
    max_attempts: int

    @property
    def live_fetch_enabled(self) -> bool:
        """Return True when both the feature flag and live-network gate are on."""

        return self.enabled and self.allow_live_network


def load_wbes_settings(project_root: Path | None = None) -> WbesSettings:
    """Load WBES flags from the environment. All live work is off by default."""

    root = Path(project_root) if project_root is not None else Path(
        os.getenv("PSP_PROJECT_ROOT", Path.cwd())
    )
    wbes_root = root / "data" / "wbes"
    block_minutes = int(os.getenv("WBES_BLOCK_MINUTES", "15"))
    block_count = int(os.getenv("WBES_BLOCK_COUNT", "96"))
    return WbesSettings(
        enabled=_as_bool(os.getenv("WBES_ENABLED"), False),
        allow_live_network=_as_bool(os.getenv("WBES_ALLOW_LIVE_NETWORK"), False),
        allow_five_minute=_as_bool(os.getenv("WBES_ALLOW_FIVE_MINUTE"), False),
        write_timescale=_as_bool(os.getenv("WBES_WRITE_TIMESCALE"), False),
        project_root=root,
        catalog_path=Path(
            os.getenv("WBES_CATALOG_PATH", root / "config" / "wbes_sources.yaml")
        ),
        raw_dir=Path(os.getenv("WBES_RAW_DIR", wbes_root / "raw")),
        drop_dir=Path(os.getenv("WBES_DROP_DIR", wbes_root / "drop")),
        sqlite_path=Path(
            os.getenv("WBES_SQLITE_PATH", wbes_root / "wbes_schedule.sqlite")
        ),
        username=os.getenv("WBES_USERNAME", ""),
        password=os.getenv("WBES_PASSWORD", ""),
        session_cookie=os.getenv("WBES_SESSION_COOKIE", ""),
        user_agent=os.getenv(
            "WBES_USER_AGENT",
            "Mozilla/5.0 (compatible; PSP-WBES-probe/0.1)",
        ),
        postgres_dsn=os.getenv(
            "POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/power_kg",
        ),
        block_count=block_count,
        block_minutes=block_minutes,
        http_timeout_seconds=float(os.getenv("WBES_HTTP_TIMEOUT_SECONDS", "20")),
        max_attempts=int(os.getenv("WBES_HTTP_MAX_ATTEMPTS", "2")),
    )
