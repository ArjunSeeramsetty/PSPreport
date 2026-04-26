---
name: psp-source-adapters
description: Use when adding or changing public PSP/RLDC/RPC/NLDC source discovery and download connectors, including deterministic SRLDC URLs, NRLDC document APIs, retry/backoff behavior, local raw PDF storage, and avoidance of browser automation for public sources.
---

# PSP Source Adapters

## Source Priority
- Prefer deterministic URL construction first.
- Prefer documented or discoverable JSON/API endpoints second.
- Use browser automation only when deterministic/API access is unavailable or blocked.
- Keep WBES separate behind the `wbes-controlled-access` rules.

## SRLDC
- Construct URLs as `https://srldc.in/var/ftp/reports/psp/{year}/{MonYY}/{DD-MM-YYYY}-psp.pdf`.
- Use retry with bounded exponential backoff for transient failures.
- Store downloaded PDFs under `downloads/SRLDC_PSP` or configured raw storage.

## NRLDC
- Prefer the daily PSP document API at `/get-documents-list/111`.
- Extract CSRF/session metadata from the daily PSP page before calling the API.
- Prefer report date from `dailyDDMMYY` in filename/title over upload/listing date.

## Operational Rules
- Preflight with `HEAD` where supported, but tolerate portals that require direct `GET`.
- Reject empty payloads.
- Compute content hash before persistence.
- Preserve source URL, fetched time, content length, and last-modified when available.
