from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path


def load_env(path: Path = Path(".env")) -> None:
    """Small .env reader; existing environment variables take precedence."""
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    base_url: str = "http://p94.itapi.pl:8000/v1"
    model: str = ""
    api_key: str = ""
    memory_budget: int = 8000
    timeout: float = 60
    seed: int = 42
    vision_range: int = 6
    max_plan: int = 5
    thinking_interval: float = 3.0
    agent_count: int = 1

    def __post_init__(self) -> None:
        if not 600 <= self.memory_budget <= 32000:
            raise ValueError("Budżet pamięci musi wynosić od 600 do 32000.")
        if not 1 <= self.vision_range <= 10:
            raise ValueError("Zasięg wzroku musi wynosić od 1 do 10.")
        if not 1 <= self.max_plan <= 8:
            raise ValueError("Plan musi mieć od 1 do 8 działań.")
        if not math.isfinite(self.thinking_interval) or not .1 <= self.thinking_interval <= 60:
            raise ValueError("Odstęp między analizami musi wynosić od 0,1 do 60 sekund.")
        if not 1 <= self.agent_count <= 8:
            raise ValueError("Liczba istot musi wynosić od 1 do 8.")
        if not 1 <= self.timeout <= 300:
            raise ValueError("Timeout musi wynosić od 1 do 300 sekund.")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("Adres API musi zaczynać się od http:// lub https://.")

    @classmethod
    def from_env(cls) -> Settings:
        load_env()
        return cls(
            base_url=os.getenv("LIFEAI_BASE_URL", cls.base_url).rstrip("/"),
            model=os.getenv("LIFEAI_MODEL", ""),
            api_key=os.getenv("LIFEAI_API_KEY", ""),
            memory_budget=int(os.getenv("LIFEAI_MEMORY_BUDGET", "8000")),
            timeout=float(os.getenv("LIFEAI_TIMEOUT", "60")),
            seed=int(os.getenv("LIFEAI_SEED", "42")),
            agent_count=int(os.getenv("LIFEAI_AGENTS", "1")),
            thinking_interval=float(os.getenv("LIFEAI_THINK_INTERVAL", "3")),
        )
