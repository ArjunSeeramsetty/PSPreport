# Blockers and Solutions

## 1) JS-heavy portals and changing links
- **Blocker:** Dynamic pages and client-side rendering break static scrapers.
- **Solution:** Use Playwright capture profile per source; record network endpoints and replay stable JSON calls via `httpx`.

## 2) WBES authentication and session controls
- **Blocker:** Login-gated sessions, possible IP restrictions.
- **Solution:** Use read-only service account, secure secret storage, session refresh flow, and onboarding checklist before scheduled runs.

## 3) CAPTCHA/OTP/manual checkpoints
- **Blocker:** Fully unattended login can fail.
- **Solution:** Human-in-loop approval window for token refresh; fallback manual upload path to keep Bronze feed running.

## 4) PDF/Excel schema drift
- **Blocker:** Headers and table geometry vary often.
- **Solution:** Parser versioning + template registry + golden-file regression tests per source family.

## 5) Low-quality scans
- **Blocker:** OCR confidence drops and causes false values.
- **Solution:** Confidence thresholding + selective OCR retry; use paid OCR only for failures.

## 6) Retroactive revisions in REA/DSM
- **Blocker:** New corrections can overwrite earlier values.
- **Solution:** Bitemporal model (`valid_from`, `valid_to`, `version_no`) and immutable lineage logs.

## 7) Cross-source naming inconsistencies
- **Blocker:** Same entity appears with variant names.
- **Solution:** Canonical entity index + fuzzy matcher + adjudication queue.

## 8) Source downtime and throttling
- **Blocker:** Scheduled jobs fail during outages.
- **Solution:** Retry with backoff, source health score, and delayed catch-up jobs.

## 9) Legal/compliance uncertainty
- **Blocker:** Access terms differ by portal.
- **Solution:** Respect site terms and robots; maintain source attribution and written approvals for restricted endpoints.

## 10) Graph bloat from block-level storage
- **Blocker:** Storing 15-min points in graph destroys traversal performance.
- **Solution:** Keep block-level points in Timescale; graph holds topology and reference metadata only.

