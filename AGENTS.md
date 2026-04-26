# Coding Agent Rules

## Objective
Produce production-quality Python code for the Indian power-system ingestion pipeline. Keep the project readable, modular, replayable, and easy to validate.

## Coding Standards
- Follow PEP 8 and prefer explicit, readable code over clever code.
- Reuse existing modules and project patterns before introducing new abstractions.
- Keep files focused on a single responsibility.
- Avoid duplicate logic. Refactor shared behavior into utilities only when reuse is real.
- Preserve backward compatibility unless a task explicitly allows breaking changes.

## Documentation
- Add concise docstrings to every new public module, class, function, and method.
- Docstrings should explain purpose, important inputs/outputs, and relevant failure behavior.
- Do not add new markdown files unless explicitly requested.

## Logging
- Use the standard `logging` module for runtime diagnostics.
- Do not use `print()` inside package code.
- Log only meaningful operational events, recoverable anomalies, decisions, and failures.
- Do not log secrets, credentials, tokens, or sensitive payloads.

## Project Structure
- Put reusable code under `src/psp_pipeline/`.
- Keep `scripts/` as thin CLI wrappers only.
- Treat `archive/` as read-only reference material.
- Runtime artifacts belong under `data/` or `downloads/` and should not become source code dependencies.
- Prefer local-first PSP workflows: download reports, store raw artifacts, parse from local paths, then load normalized data.

## PSP Domain Rules
- For deterministic PSP downloads, first check archive patterns and current acquisition modules.
- For SRLDC, prefer deterministic URL construction before page scraping.
- For NRLDC, prefer the document API path when available before browser automation.
- Store raw extracted lines/cells alongside normalized observations when parser coverage is still evolving.
- Keep current metric naming style: `all_india_*`, `regional_*`, and source-specific prefixes only when needed.
- Use LiteParse through `npx -y @llamaindex/liteparse` when PDF parsing requires local spatial extraction, OCR fallback, screenshots, or JSON bounding boxes.
- On this Windows workspace, set `TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata` before using LiteParse OCR, or use `scripts/run_liteparse.ps1`.
- Treat LiteParse output as a parser aid until it is validated against known PSP fixtures; do not replace source-specific parsers without tests.

## Project Skills
- Use `indian-power-psp` for general PSP ingestion work.
- Use `psp-source-adapters` for source discovery and report downloads.
- Use `psp-parser-validation` for parser, OCR, fixture, and validation changes.
- Use `airflow-pipeline-ops` for DAG and stage orchestration changes.
- Use `bitemporal-modeling` for TimescaleDB/PostgreSQL schema and temporal semantics.
- Use `neo4j-graph-sync` for graph constraints, Cypher, and topology sync.
- Use `wbes-controlled-access` for any WBES planning or implementation.
- Use `liteparse` for local spatial document parsing and OCR fallback.

## Temporary Artifacts
- If temporary scripts or files are created for inspection, migration, or generation, delete them before completing the task.
- Before finishing, confirm no unnecessary scratch files, duplicated scripts, or dead imports remain.

## Quality Checks
Before marking work complete:
- Run relevant tests for changed code.
- Run syntax or import checks when tests are not available.
- Review the final diff for unnecessary files, duplicated logic, unused imports, and backward compatibility.

## Done Criteria
A task is complete only when:
1. The requested behavior is implemented.
2. Code follows these rules.
3. Relevant checks pass or any skipped checks are clearly reported.
4. No unnecessary files remain.
