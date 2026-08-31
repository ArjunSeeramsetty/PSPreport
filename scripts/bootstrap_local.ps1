$ErrorActionPreference = "Stop"

Write-Host "Starting local stack (TimescaleDB, Neo4j, MinIO, Airflow)..."
docker compose up -d timescaledb neo4j minio airflow-postgres airflow-init airflow-webserver airflow-scheduler

Write-Host "Done."
Write-Host "Apply greenfield Timescale schema and backfill SQLite with:"
Write-Host "  python scripts/bootstrap_timescale_from_sqlite.py --db data/sqlite/all_rldc_daily.sqlite --recreate-schema"
Write-Host "Airflow: http://localhost:8080 (admin/admin)"
Write-Host "Neo4j: http://localhost:7474"
Write-Host "MinIO: http://localhost:9001 (minioadmin/minioadmin)"

