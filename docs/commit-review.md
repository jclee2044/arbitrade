# Modular commit review · November 16, 2026

This scope supersedes the older single-commit proposal below. User requested
all recent changes as modular commits, then requested the demo/report/README
updates before committing. Student approved these four groups and pushing on November 16, 2026
(prompt104). `report.md` is untracked and ignored; it must never be staged.
The execution record below supersedes the prior pending-review state.

Approved commits, in order:

1. **Add provider history and observed-volume handling** — backend candle,
   history, live, replay, indicator-store and provider-history changes and their
   tests; history/backfill/provider/recorded-volume fixtures and smoke checks;
   candle/replay documentation and market-data evidence.
2. **Add classroom chart decision API** — classroom backend/test and Vue
   component, placeholder `.env.example`, classroom fixture and smoke checks,
   classroom decision guide and corresponding screenshots.
3. **Improve chart tools, workspace and connection recovery** — shared backend
   route wiring in `backend/main.py` (after its dependencies above), remaining
   Vue components/styles, chart gestures/drawings/captures, browser regression
   drivers and decision fixture updates; related decision/review/chart guides
   and workspace screenshots.
4. **Add assignment demo and update project records** — original supplied
   `demos/Assignment 4.1 Demo.mov`, `.gitignore` report exclusion, README,
   AGENTS.md, design pipeline, Part 4.1 evidence guide, prompt records 51–104,
   verification, handoff and this review. The report itself stays local.

Some features share route wiring and chart components, so the complete series
should be reviewed and validated together. Existing local commit `d2f46b7`
remains unchanged. No dependency manifests/lockfiles are changed by this task.

Fresh artifact validation: original/copy SHA-256 equality, all local links in
README/report/design pipeline, report untracked/ignored, demo eligible for Git,
and `git diff --check` passed. Fresh execution checks also passed: all 115 backend tests, frontend build
and saved-Yahoo recorded-volume browser SmokeTest. See verification.md. Playback and published GitHub video access remain unverified.

---

## Historical proposal (superseded)

# Proposed commit · November 15, 2026

Proposed message: `Improve chart history, drawing tools and trading workspace`.

Include all current tracked modifications and untracked project files: prompts
51–88, backend provider history and classroom decision API, chart gestures and
drawing tools, interval indicators, AI and paper-trading navigation, menu styling,
fixtures, smoke checks, screenshots, README, design pipeline, verification and
handoff records. `.env.example` contains a placeholder only. Local credentials,
installed packages, generated bundles, databases and history caches stay ignored.

The existing local commit `d2f46b7` (`Redesign Arbitrade workspace with indicators
and signals`) is also ahead of origin/main and would be included in the push.
Current branch: main; proposed destination: its configured upstream origin/main.

Review changes in the workspace diff before approving the commit. This record
does not claim that student review has occurred. No commit or push has run.

Fresh validation: frontend production build passed, nine provider-history and
classroom-decision backend tests passed with host access, and git diff --check
passed. A common credential-pattern scan found no matches; this was a limited
pattern check. Existing UI SmokeTest results are recorded in verification.md;
the browser suites were not rerun for this commit-preparation request.
