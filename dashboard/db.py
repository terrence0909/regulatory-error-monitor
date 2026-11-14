"""Database access for the dashboard: one small function, one connection per query."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg2

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path):
    """Read KEY=VALUE lines from .env. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")


def query(sql: str, params=None) -> pd.DataFrame:
    """Run a SELECT and return the result as a table."""
    conn = psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        dbname=os.environ["POSTGRES_DB"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            rows = cur.fetchall()
    finally:
        conn.close()
    frame = pd.DataFrame(rows, columns=columns)
    for col in frame.columns:  # Postgres numerics arrive as Decimal; charts want floats
        if frame[col].dtype == object and len(frame) and type(frame[col].iloc[0]).__name__ == "Decimal":
            frame[col] = frame[col].astype(float)
    return frame