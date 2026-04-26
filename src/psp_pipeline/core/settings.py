from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    raw_bucket: str
    postgres_dsn: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    wbes_username: str
    wbes_password: str


def load_settings() -> AppSettings:
    project_root = Path(os.getenv("PSP_PROJECT_ROOT", Path.cwd()))
    return AppSettings(
        project_root=project_root,
        raw_bucket=os.getenv("RAW_BUCKET", "psp-raw"),
        postgres_dsn=os.getenv(
            "POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/power_kg",
        ),
        neo4j_uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
        neo4j_password=os.getenv("NEO4J_PASSWORD", "neo4j-password"),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        minio_secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        wbes_username=os.getenv("WBES_USERNAME", ""),
        wbes_password=os.getenv("WBES_PASSWORD", ""),
    )

