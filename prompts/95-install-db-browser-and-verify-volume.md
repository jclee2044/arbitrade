# Install DB Browser and verify minute volume · November 16, 2026

Student: “yes install it, and look into why the minute volume isn't showing so
we can verify it for the report.”

Approval covers the previously proposed Omarchy package sqlitebrowser3.13.1-3
and its resolved dependencies via omarchy pkg add sqlitebrowser. Investigate
actual saved Yahoo cumulative-volume data, correct in-scope candle handling,
test duplicates/revisions/out-of-order/missing/reset behavior and the visible
chart. Preserve existing work and distinguish recorded data from a fresh live
capture, and observed counter deltas from provider-reported bar volume. Update
report and supporting evidence with verified findings. No commit authorized.
