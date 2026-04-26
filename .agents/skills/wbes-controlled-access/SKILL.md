---
name: wbes-controlled-access
description: Use when planning or implementing WBES controlled-access integration, Playwright login probes, credential/session handling, endpoint discovery, 96-block schedules, regulatory validation, or feature-gated access to Grid-India WBES systems.
---

# WBES Controlled Access

## Compliance Boundary
- Treat WBES as controlled-access infrastructure, not public scraping.
- Do not call WBES from the public daily ingestion pipeline.
- Gate all WBES code behind explicit environment feature flags.
- Require credentials, permission, and IP/network prerequisites before live automation.

## Security Rules
- Never hardcode usernames, passwords, headers, cookies, bearer tokens, or session IDs.
- Load secrets from ignored environment files or secure runtime configuration.
- Redact DOM dumps, screenshots, HAR files, and logs before storing them.
- Do not commit WBES-derived protected data into fixtures.

## Scheduling Semantics
- Model each day as 96 15-minute blocks unless a future regulatory change is explicitly implemented.
- Validate block timestamps and block numbers.
- Keep WBES schedules in Timescale/Postgres, not Neo4j.

## Automation Strategy
- Use Playwright only for login/session establishment and endpoint discovery.
- Prefer captured JSON/XHR endpoints for repeatable extraction after session setup.
- Implement checkpointing and resumable date/block loops.

## Done Criteria
- WBES code is disabled by default.
- Tests use mocked sessions and fixtures, not live credentials.
- Public ingestion remains runnable without WBES configuration.
