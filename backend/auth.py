import os
from pathlib import Path

LICHESS_HOST = "https://lichess.org"
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ENV_PATHS = (
    BACKEND_DIR / ".env",
    BACKEND_DIR / ".env.local",
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / ".env.local",
)
ORIGINAL_ENV_KEYS = set(os.environ)


def _load_env_local() -> None:
    for env_path in ENV_PATHS:
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in ORIGINAL_ENV_KEYS:
                continue
            os.environ[key] = value.strip().strip("'\"")


_load_env_local()
