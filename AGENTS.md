# Working instructions for Arbitrade

## Scope and review

- Work inside `/home/jlrj/Documents/arbitrade` and inspect relevant files before editing.
- Preserve existing work and inspect Git status before making changes. If Git
  reports that this is not a repository, record that fact; do not initialize
  or repair Git without authorization.
- Show changes for student review before a commit. Do not commit without review.
- Build toward a Python backend, Vue frontend, and FastAPI transport layer.
- Reuse the confirmed existing Python environment: `/usr/bin/python`.
  Do not create or recreate a virtual environment by default.
- Keep credentials out of source code, prompts, logs, and Git. Use placeholders
  in documentation and never print secret values during inspection.

## Prompt and result records

Save each major prompt under `prompts/`, preserving existing numbering and
files. Reuse an existing copy instead of overwriting it. Record observed
results, commands, failures, and outstanding checks in `docs/verification.md`.
Keep the README and design pipeline aligned with what actually exists.

## Tools and packages: CHECK / TAKE ACTION / VERIFY

Use this procedure whenever a tool or package is needed.

### CHECK

Inspect the operating system, active Python interpreter and environment,
Node.js, package managers, dependency files, and lockfiles. Check which tools
and packages are already available. Reuse the existing Python environment.

### TAKE ACTION

For each missing dependency needed for the current task, explain its purpose,
compatible version, exact command, installation target, and files it will
change. Obtain student approval before installing software or changing a
dependency manifest or lockfile. Verify compatibility before proposing a
version. Do not install dependencies merely to finish documentation.

### VERIFY

Run the smallest relevant version, import, or build check in the intended
environment. Record its command, expected result, and observed result in
`docs/verification.md`. Identify checks that still need to run. Do not report
unexecuted checks as passes.

## SmokeTest

SmokeTest is a repeatable check that runs without source edits. Document one
command that runs it once application code exists. Before then, explicitly
record that no runnable SmokeTest exists.

Once a feature has a UI, SmokeTest must start local services, open a browser,
perform a user operation, and compare the visible result with the expected
result. Check stored data when relevant. Clean up services started by the test
and record failures as well as passes in `docs/verification.md`.

## AutoLoop

On a failed check, inspect the failure, make the smallest in-scope correction,
and rerun the check. Stop on success, after five correction cycles, or when
further permission is needed. Record the outcome and any remaining failure.

## Market-data verification

- Keep original Yahoo observations and receipts immutable. Source-time ties
  do not identify corrections. For volume, nondecreasing cumulative counters
  may advance in first-receipt order at one timestamp; decreasing or invalid
  baselines and missing data must remain unavailable.
- Identify observed counter deltas separately from downloaded Yahoo bar volume.
  Never add the two. Use `scripts.recorded_volume_smoke` for the saved-Yahoo
  SQL/HTTP/WebSocket/chart check; it uses disposable storage and a frozen capture.
  A saved-data pass is not a new live-feed observation or a DB Browser screenshot.

## Handoff

Follow `handoffs/create-handoff.md` to update `handoffs/current.md` at session
end and to verify the recorded state on resumption.
