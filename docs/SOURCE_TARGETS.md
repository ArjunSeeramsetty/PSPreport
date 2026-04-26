# Source Targets and Load Plan

## RLDC Operational Layer (Bronze-first)
- SRLDC
  - `https://www.srldc.in/Daily-Reports`
  - `https://www.srldc.in/Weekly-Reports`
  - `https://www.srldc.in/Monthly-Reports`
- NRLDC
  - `https://www.nrldc.in/`
  - `https://oms.nrldc.in/outageReport/`
- NERLDC
  - `https://www.nerldc.in/power-supply-position-psp-report/`
  - `https://www.nerldc.in/weekly-report/`
  - `https://www.nerldc.in/monthly-report/`
- WRLDC
  - `https://www.wrldc.in/`
  - `https://portal.wrldc.in/Trippingnew/`
- ERLDC
  - `https://erldc.in/` (JS-heavy, capture with Playwright)

## RPC Settlement Layer (Silver/Gold)
- ERPC: `https://erpc.gov.in/en/commercial/`
- NRPC: `https://www.nrpc.gov.in/`
- SRPC: `https://www.srpc.kar.nic.in/html/recent_uploads.html`
- WRPC: `https://www.wrpc.gov.in/`
- NERPC: `https://nerpc.gov.in/`

## NLDC/National Layer
- GRID-INDIA portal: `https://www.grid-india.in/`
- Priority families: daily PSP, inter-regional transfer, TTC/ATC, monthly operations.

## WBES (Controlled Access)
- Endpoint: `https://newwbes.grid-india.in/`
- Status: implemented as controlled source in registry.
- Current action: onboarding only (credential + permission + possible allowlist), then activate Playwright connector.

