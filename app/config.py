"""Central settings. Everything env-driven so the same image runs locally and hosted."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./smartrental.db"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # worker cadence
    overdue_scan_minutes: int = 5
    anomaly_scan_minutes: int = 15
    forecast_hour_utc: int = 2

    # demo simulator
    simulator_enabled: bool = True
    simulator_tick_seconds: int = 5
    # 3 minutes of machine time per tick: fast enough to watch, slow enough
    # that a demo session never produces an impossible day.
    simulator_hours_per_tick: float = 0.05

    # condition photos captured at check-out / check-in
    media_root: str = "./media"
    max_photo_mb: float = 8.0

    # Mira -- the dashboard assistant, backed by Google Gemini.
    # No key means no Mira: the endpoint reports itself unconfigured and the
    # UI hides the button rather than offering something that cannot answer.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout_seconds: float = 30.0
    # Each round is one model call plus the tool results it asked for. Four is
    # enough for "which assets are overdue, and what do they cost me" and low
    # enough that a confused model cannot spin.
    mira_max_tool_rounds: int = 4

    # business rules
    idle_ratio_threshold: float = 0.70
    idle_streak_days: int = 3
    stale_ping_hours: int = 48
    overdue_reminder_days: int = 3

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
