"""Runtime settings, read from the environment or a .env file at the repo root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    dbPath: Path
    ollamaUrl: str
    model: str
    numCtx: int
    temperature: float
    repeatLastN: int
    repeatPenalty: float
    requestTimeout: int


def loadSettings() -> Settings:
    db = os.environ.get("NSIGHT_DB", "data/interim/nsight.duckdb")
    dbPath = Path(db)
    if not dbPath.is_absolute():
        dbPath = REPO_ROOT / dbPath
    return Settings(
        dbPath=dbPath,
        ollamaUrl=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        model=os.environ.get("NSIGHT_MODEL", "medgemma"),
        # ollama defaults to a small context and silently cuts the front of long prompts
        numCtx=int(os.environ.get("NSIGHT_NUM_CTX", "16384")),
        temperature=float(os.environ.get("NSIGHT_TEMPERATURE", "0")),
        # greedy decoding loops once a repeated block outgrows the default 64-token window
        repeatLastN=int(os.environ.get("NSIGHT_REPEAT_LAST_N", "512")),
        repeatPenalty=float(os.environ.get("NSIGHT_REPEAT_PENALTY", "1.1")),
        requestTimeout=int(os.environ.get("NSIGHT_TIMEOUT", "900")),
    )
