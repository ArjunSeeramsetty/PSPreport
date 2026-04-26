---
name: indian-power-psp
description: Use when working on this repository's Indian power-system PSP ingestion pipeline, especially deterministic NLDC/SRLDC/NRLDC report downloads, local PDF-first parsing, SQLite staging, Timescale/Neo4j integration, parser validation, and reuse of archive patterns without copying legacy scripts wholesale.
---

# Indian Power PSP Pipeline

## Core Workflow
1. Read `AGENTS.md` before changing project code.
2. Treat `archive/` as read-only reference material.
3. Prefer this flow for PSP work:
   - discover or construct report URLs
   - download PDFs to local storage
   - validate report family
   - extract raw lines/cells
   - extract normalized observations
   - persist with lineage and validation results
4. Keep scripts thin. Put reusable logic under `src/psp_pipeline/`.

## Archive Patterns To Reuse
- Use `archive/Create DB/get_report_url.py` as a reference for deterministic date/month iteration and local PDF download workflows.
- Use `archive/pdf_orchestrator.py` as a reference for chronological local processing, commit checkpoints, and failure policy.
- Use `archive/Create DB/modular_psp_parser.py` as a reference for table classification and PSP table transformations.
- Use archive database/schema files as references for fact/dimension design, not as direct runtime dependencies.

## Source Strategy
- SRLDC: prefer deterministic URLs using `{year}/{MonYY}/{DD-MM-YYYY}-psp.pdf`, then retry missing dates with backoff, then listing crawl only if needed.
- NRLDC: prefer the daily PSP document API and CSRF/session metadata where available.
- Other RLDCs: keep future implementations behind the same adapter/parser interface.
- WBES: treat as controlled-access and keep separate from public PSP ingestion.

## Parser Strategy
- Keep source-specific parser logic explicit, such as `SRLDCPSPParser` and `NRLDCPSPParser`.
- Store raw extracted lines/cells before relying on normalized field coverage.
- Keep current metric naming convention: `all_india_*`, `regional_*`, and unambiguous units such as `_mw`, `_mu`, `_pct`, `_hz`.
- Add validation rules near parser logic and keep tolerances documented in code.
- Use the repo-local `liteparse` skill when PDF parsing needs spatial extraction, OCR fallback, screenshots, or structured JSON beyond `pdfplumber`/Camelot.
- Prefer invoking LiteParse through `npx -y @llamaindex/liteparse ...` in this workspace because the global `lit` executable may not be on PATH.
- On this Windows workspace, set `TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata` before OCR, or use `scripts/run_liteparse.ps1`.
- Use LiteParse as a fallback or forensic tool first; keep deterministic source-specific parsers as the production path until LiteParse outputs are validated against known PSP fixtures.

## Quality Bar
- Add tests or focused verification for date parsing, URL construction, report-family validation, extraction coverage, and persistence.
- Avoid adding one-off scripts when a reusable module or existing CLI can be extended.
- Before finishing, check for temporary files, duplicated code, unused imports, and broken old import paths.
