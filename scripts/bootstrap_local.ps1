$ErrorActionPreference = "Stop"

Write-Host "Starting local stack (TimescaleDB, Neo4j, MinIO, Airflow)..."
docker compose up -d timescaledb neo4j minio airflow-postgres airflow-init airflow-webserver airflow-scheduler

Write-Host "Done."
Write-Host "Airflow: http://localhost:8080 (admin/admin)"
Write-Host "Neo4j: http://localhost:7474"
Write-Host "MinIO: http://localhost:9001 (minioadmin/minioadmin)"

