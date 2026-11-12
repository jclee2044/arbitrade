# AI-use record

## November 11, 2026 · Indicators and Signals

The student chose the tabbed emerald sidebar, parchment header, six independent SMA/EMA periods and eight chart intervals. Codex adapted the Vue controls, implemented the EMA and exchange-calendar aggregation in Python, and used the existing Chromium suite to exercise recorded and constructed data. The student-facing summary displays a reviewed decision only for its selected candle. A regression check verifies that switching to an earlier candle with insufficient history removes the previous proposal and that Voice selects the saved result. [Prompt](prompts/49-implement-indicators-signals-workspace.md) · [Verification](docs/verification.md#indicators-and-signals-workspace).

## November 11, 2026 · Trading desk redesign

The student selected the ivory chart, parchment summary, emerald navigation, and light-blue diamond. The student requested a top-right Paper trading control, the Indicators label, continued access to existing features, and alignment with the supplied assignment. [Prompt 43](prompts/43-redesign-workstation.md).

OpenAI Codex, a GPT-6-based coding agent in the Codex desktop app, inspected the project, implemented the Vue layout, adapted the browser checks, and prepared the documentation and screenshots. Vite built the frontend. Playwright drove Chromium to inspect the actual application and exercise the simulated workflows. The feature checks used controlled model replies and synthetic microphone input. [Verification and evidence](docs/verification.md#trading-desk-redesign--november-11-2026).

One implementation decision was to keep the chart, proposal, automation, and voice components mounted while a different panel is open. Unmounting them runs cleanup that can discard a frozen chart or end a voice session. The browser checks returned to the same chart capture and active voice session, and followed an automated paper fill while viewing Chart. [Workspace implementation](frontend/src/main.js) · [Browser results](docs/screenshots/workstation-redesign/report.json).
