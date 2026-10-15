"""Shared configuration. Shell environment takes precedence over the local .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)


def env_path(name, default):
    path = Path(os.getenv(name, default)).expanduser()
    return path if path.is_absolute() else ROOT / path
