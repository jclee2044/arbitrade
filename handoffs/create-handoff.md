# Create and resume a handoff

1. At session end, write `handoffs/current.md` with the project purpose and
   root, agreed constraints, files created or changed, commands and observed
   check results, outstanding questions, blockers, and the next task. Link to
   `docs/verification.md`; distinguish completed work from planned work and
   omit credentials.
2. When resuming, read `AGENTS.md` and `handoffs/current.md`, inspect the actual
   files and Git status, and rerun the smallest relevant recorded checks.
   Reconcile any differences before editing. Verify the active interpreter
   and obtain required dependency approval before installations or manifest
   and lockfile changes.
