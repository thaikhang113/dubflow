# Retention & Adoption Analysis (Aptabase `session_start` events)

**Period:** Jun 29 – Jul 10  
**Source:** Aptabase CSV exports of `session_start` events, joined on anonymous `installId` (not session ID).  
**Totals:** 8,590 events across 1,810 installs.

## Summary

Merged events showed **38–47%** of Jul 1–4 cohorts returned on another day within 3 days. WAU reached **1,473** unique installIds for Jul 4–10 (**+111%** vs the prior week). A sharp **Jul 9 spike** (398 new installs, 679 DAU) was observed alongside shifting adoption toward **grok-4.5** and strong engagement depth (**41.5%** multi-day users).

## Cohort retention table

| Cohort | New installs (first `session_start`) | Returned within D+1…D+3 | 3-day retention | D+1 return rate |
|--------|--------------------------------------|-------------------------|-----------------|-----------------|
| Jul 1  | 166                                  | 78                      | **47.0%**       | 36.1%           |
| Jul 2  | 170                                  | 73                      | **42.9%**       | 29.4%           |
| Jul 3  | 130                                  | 49                      | **37.7%**       | 23.1%           |
| Jul 4  | 90                                   | 39                      | **43.3%**       | 27.8%           |

## Retention diagram

```mermaid
%% Retention Cohorts — Grok Build VS Code
%% Data source: Aptabase session_start events (keyed by anonymous installId)
%% "New installs" = day of an installId's first real session_start
flowchart TB
    classDef cohort fill:#bae6fd,stroke:#0369a1,color:#0c4a6e
    classDef retained fill:#86efac,stroke:#166534,color:#14532d
    classDef d1 fill:#fde047,stroke:#854d0e,color:#713f12
    classDef wau fill:#c026ff,stroke:#581c87,color:#f3e8ff,stroke-width:3px

    subgraph Cohorts["New installs by cohort"]
        direction TB
        C1["Jul 1<br/>166 new"]:::cohort
        C2["Jul 2<br/>170 new"]:::cohort
        C3["Jul 3<br/>130 new"]:::cohort
        C4["Jul 4<br/>90 new"]:::cohort
    end

    subgraph Retained["Returned within D+1…D+3"]
        direction TB
        R1["78 users<br/>**47.0%**"]:::retained
        R2["73 users<br/>**42.9%**"]:::retained
        R3["49 users<br/>**37.7%**"]:::retained
        R4["39 users<br/>**43.3%**"]:::retained
    end

    subgraph D1Rates["D+1 return rate"]
        direction TB
        D1["36.1%"]:::d1
        D2["29.4%"]:::d1
        D3["23.1%"]:::d1
        D4["27.8%"]:::d1
    end

    WAU["**WAU Jul 4–10**<br/>1,473 unique installIds<br/>(+111% vs prior week)"]:::wau

    C1 -->|"47.0%"| R1
    C2 -->|"42.9%"| R2
    C3 -->|"37.7%"| R3
    C4 -->|"43.3%"| R4

    R1 --> D1
    R2 --> D2
    R3 --> D3
    R4 --> D4

    R1 -.->|"48% still active 9 days later"| WAU
```

## Key observations

- Short-term retention is healthy: mid-to-high 30s to mid-40s percent of new installs return within three days.
- The bulk of 3-day returns happens on D+1; D+2/D+3 add the remainder.
- For the Jul 1 cohort, 48% of the users who returned in the 3-day window were still active nine days later.
- WAU more than doubled week-over-week despite (or alongside) the Jul 9 spike.
- 41.5% multi-day users indicates good depth of engagement beyond one-off trials.
- Model mix continues shifting toward newer `grok-4.5` builds.

## Methodology

- **Cohort definition**: the calendar day of the *earliest* `session_start` for each distinct `installId`.
- **"Returned"**: at least one later `session_start` whose date is D+1, D+2, or D+3 relative to the cohort day.
- **WAU**: count of unique `installId`s that produced ≥1 `session_start` inside the Jul 4–10 window.
- **DAU / spikes**: derived from per-day unique `installId` counts in the exports.
- Only real user-initiated sessions are counted (the extension deliberately suppresses `session_start` for the hidden plan-mode primer and for primer-only/empty sessions).
- No client-side aggregation or retention math exists in the extension; this is purely post-hoc analysis of exported event CSVs.

## Related code & docs

- Event shape and guards: [src/telemetry.ts](../src/telemetry.ts)
- Privacy design & what is (not) sent: [docs/privacy.md](../docs/privacy.md)
- Probe that fires real events (to the dev project): [scripts/telemetry-probe.cjs](../scripts/telemetry-probe.cjs)
- Install ID generation & first-send gate: `src/sidebar.ts` (search `INSTALL_ID_KEY` and `isFirstSend`)

The extension's telemetry is intentionally minimal: one fire-and-forget `session_start` carrying only `installId` + `mode`/`model`/`effort` (plus standard system fields). Richer cohort or funnel analysis is performed offline on Aptabase exports.

---

*Analysis performed on merged CSV exports using `installId` as the user key. Numbers are as captured in the source data.*