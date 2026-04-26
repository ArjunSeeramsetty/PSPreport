---
name: psp-parser-validation
description: Use when changing PSP PDF parsing, raw line/cell extraction, OCR fallback, field aliases, source-specific parser classes, validation tolerances, or extraction tests for SRLDC, NRLDC, NLDC, or future RLDC reports.
---

# PSP Parser Validation

## Parser Workflow
- Parse from local PDFs, not live URLs.
- Store raw extracted lines and cells before relying on normalized observations.
- Keep source-specific parser behavior explicit, such as `SRLDCPSPParser` and `NRLDCPSPParser`.
- Use LiteParse only as a forensic fallback or spatial/OCR aid until fixtures prove it should be promoted.

## Fixture-First Rule
- Every parser change should be checked against at least one known local fixture.
- Prefer small fixture sets spanning multiple months when format drift is likely.
- Avoid "fixing" one report by breaking another; compare extraction coverage before and after.

## Metric Naming
- Keep current names: `all_india_*`, `regional_*`, and explicit unit suffixes like `_mw`, `_mu`, `_hz`, `_pct`.
- Do not use ambiguous names like `value`, `demand`, or `generation` without source/entity/unit context.

## Validation Rules
- Frequency percentage bands should sum close to 100%.
- Station average MW should reconcile against net MU over 24 hours within a small rounding tolerance.
- State or regional totals should reconcile against row-level components where the report exposes control totals.
- Persist validation failures; do not silently discard suspicious rows.
