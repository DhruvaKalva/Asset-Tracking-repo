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
