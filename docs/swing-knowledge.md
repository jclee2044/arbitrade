# Swing trading chart-review knowledge base

Search 33 attributed lessons from 20 distinct TheOneLanceB videos. The full [source index](#video-index) identifies each video and the material used. From the project root, run:

```sh
/usr/bin/python -m scripts.swing_knowledge "short breakdown"
```

Use `/usr/bin/python -m scripts.swing_knowledge --review "short breakdown"` to return both topic matches and required chart-context and risk material. Short topic phrases work best. All significant words must match within a lesson, so unsupported combinations can yield no topic matches. Video-level sources link to the video without a timestamp. A chapter timestamp locates a section, not an exact quote.

The CLI builds a disposable SQLite full-text index and returns up to three JSON records. For an agent, cite the supplied source URL when using the lesson, identify the hypothesis as Arbitrade's proposal, and report missing observations from the requires field. A keyword match establishes relevance only. For example, the gap lesson supports shrinking size for gap risk. A question about Lance's exact risk percentage is unanswered by these records.

## Working research specification

The [lesson records](../knowledge/swing-lessons.json) give the formulas and the evidence behind each decision. Use daily signals for a multi-session holding period. The following are test conventions.

1. Compute features after the regular-session close. Use consistent OHLC adjustments, prior-only windows for levels and stretch thresholds, and the most recent fully completed week. Calculate the 10-week SMA from weekly closes. Keep the intermediate values with the decision.
2. Evaluate continuation and reversal separately. Output a side, setup family, signal time, trigger level, invalidation price, supporting lesson IDs and reason. Wait if a required price input is missing, opposing signals coincide, or the opening price invalidates the trade. Relative volume is an optional comparison feature.
3. For a historical baseline, enter at the next regular-session open with modeled slippage. Size in whole shares using floor(risk budget / (max(stop distance, adverse gap stress) + per-share costs)), then apply buying power, portfolio and short constraints. Set budgets and stress assumptions before the test.
4. Apply the protective stop from entry. If a later session gaps through it, simulate the open plus adverse slippage. Otherwise model a touched stop at the stop with adverse slippage. For the first comparison, exit any surviving trade at the fifth session close, counting entry as day one. This common time exit is an experimental control.
5. Evaluate long and short and the two families separately on a chronological holdout. Include spread, slippage, fees and short borrow costs. Measure net expectancy per unit of planned risk, drawdown, worst overnight loss, trade count, and exposure. Compare optional weekly and volume filters against the same eligible trades without those filters. Historical results and execution integration are outstanding.

## Worked decision

Suppose the prior 20 sessions topped at 100. Today's high is 103, its low is 98, and it closes at 101. Given a bullish completed week and no opposing reversal, the continuation candidate is long. A close of exactly 100 leaves it flat. If the next open is 97 the candidate is already invalid. At an entry of 102, its structural risk is 4 per share. For an illustrative 100 dollar budget, 5 dollar gap stress and 0.10 dollar cost allowance, floor(100 / 5.10) gives 19 shares before portfolio caps. The default 1,000 dollar cash account could afford at most nine shares at 102 before other constraints. A gap below the modeled stress can lose more. This is a synthetic arithmetic example.

## Original swing framework

- Continuation and mean reversion are the creator's chapter topics. The exact lookbacks, confirmation, stops and time exit in the pilot are local hypotheses. [Mean reversion at 8:40](https://www.youtube.com/watch?v=k-X0164r66U&t=520s) · [Continuation at 10:16](https://www.youtube.com/watch?v=k-X0164r66U&t=616s) · [Creator's syndicated chapter notes](https://podcasts.apple.com/ca/podcast/the-2-swing-trading-strategies-that-made-me-millions/id1888279300?i=1000793445930)
- Timeframe agreement motivates the weekly context and daily trigger. SMA, ATR and relative volume are proposed measurements. [Alignment at 0:37](https://www.youtube.com/watch?v=k6I04ciE1KE&t=37s) · [Examples at 3:28](https://www.youtube.com/watch?v=k6I04ciE1KE&t=208s) · [Companion episode](https://www.podscan.fm/podcasts/theonelanceb-trading-podcast/episodes/how-to-use-multi-timeframe-analysis-amp-find-the-best-trading-setups)
- Overnight exposure and competition for buying power motivate separate sizing and capacity checks. Timestamps refer to the creator's chapter starts. [Sizing at 1:40](https://www.youtube.com/watch?v=bZ7-iBaI_Xw&t=100s) · [Buying power at 7:39](https://www.youtube.com/watch?v=bZ7-iBaI_Xw&t=459s) · [Companion episode transcript](https://www.podscan.fm/podcasts/theonelanceb-trading-podcast/episodes/16-years-of-swing-trading-lessons-in-12-minutes)

This corpus uses public video descriptions, chapter headings, creator articles and available companion episode passages. Individual chart frames and full video captions were not verified. Short candidates are research output only. The current paper account can sell held inventory and cannot open a short.

## Chart review contract

The read-only desk agent’s rule lookup calls topic search. The fuller review packet is available through the CLI and Python function. The controlled SDK test exercises the topic lookup path. The existing classroom Decision API still receives the chart PNG and identifying context only. Its last bar may be forming. It cannot determine an exact ATR, account risk, point-in-time borrow or prior-session history from an unlabeled image. A human-drawn line is evidence of an annotation. Verify the underlying reactions independently. [Existing capture contract](classroom-decisions.md)

For each review, retain the capture ID, symbol, exchange session, interval, as-of time, last confirmed close, source freshness and the IDs of records retrieved. Describe what is visible and what is obscured. For each candidate, record direction, holding horizon, trigger, contrary evidence, invalidation, and missing inputs. Label numerical measurements by source. Require deterministic OHLCV for comparisons near a threshold. Treat an unverified caption, a creator case study or an unlabeled overlay as insufficient evidence for a precise trading parameter.

**Worked chart contrasts.** These are synthetic examples for reviewer evaluation. All levels and conditions are research assumptions.

| Visible at the decision cutoff | Chart assessment | Evidence still needed |
|---|---|---|
| Prior highs repeatedly reject 100. Today's candle reaches 102 and closes at 99. | Wait on the long breakout. The wick tested supply, but the close returned inside. A failed long trigger alone does not establish a short. | Confirm the close and prior level from completed bars. |
| Prior floor is 50. A completed daily candle closes at 48.8, after a bearish completed week. | Short continuation candidate. Record the floor, opposing reclaim scenario, and stop on the loss side. | A chart cannot confirm borrow, financing, liquidity or account headroom. |
| A stock falls for four sessions and today's green candle is still forming below yesterday's high. | Wait on the reversal. Color and distance traveled do not confirm the proposed reclaim. | Completed confirmation bar, predeclared extreme and comparable volatility history. |
| Price gaps above resistance on earnings. Only a daily candle is visible. | A daily gap is observable. The opening-range sequence, tape absorption and headline timing are unknown. | Regular-session intraday bars, time-stamped release, same-time volume baseline. |
| An unlabeled overlay is crossed on a cropped chart with missing volume. | The line crossing can be described. Anchored VWAP, relative volume, and an exact ATR multiple remain unknown. | Legend, anchor, history, volume provenance, numerical features. |

**Validation for capital decisions.** Freeze the research rules before evaluation. Use decision-time-only chart captures including unsuccessful setups, waits, both directions, delisted names where relevant, and multiple market regimes. Keep overlapping holding periods out of adjacent training and test samples. Have independent reviewers label setups, invalidations and unknown inputs before revealing outcomes. Track directional disagreement, unsupported numeric claims, future-bar leakage, false trade calls on incomplete evidence and unjustified abstentions. Evaluate strategy returns separately after spread, slippage, borrow, halts and gap-through stops. Report sample sizes and uncertainty for each regime and compare with a simple price-only baseline. Set acceptance limits before inspecting the holdout. Run prospective shadow decisions with frozen versions and reconcile decisions to observed executable prices. No blinded image evaluation, out-of-sample performance or prospective trading results are available for this corpus.

## Video index

The evidence link identifies the creator material used for each entry. Some links point to syndicated show notes or to a public transcript excerpt of the creator speaking. The lesson record links separately to the video. Chapter-only evidence supports a topic or broad principle. The local hypothesis field contains proposed chart tests. The supplement field identifies additional evidence when used. Multiple cards from one creator are correlated observations.

| Video | Evidence consulted | Lesson IDs |
|---|---|---|
| [How to Use Multi-Timeframe Analysis & Find the Best Trading Setups](https://www.youtube.com/watch?v=k6I04ciE1KE) | [Creator companion explanation](https://theonelanceb.com/blog/how-to-use-multi-timeframe-analysis/) | alignment, features |
| [The 2 Swing Trading Strategies That Made me Millions](https://www.youtube.com/watch?v=k-X0164r66U) | [Creator syndicated chapter notes](https://podcasts.apple.com/ca/podcast/the-2-swing-trading-strategies-that-made-me-millions/id1888279300?i=1000793445930) | continuation, reversal, extension |
| [16 Years of Swing Trading Lessons in 12 Minutes](https://www.youtube.com/watch?v=bZ7-iBaI_Xw) | [Available companion transcript and creator chapters](https://podscan.fm/podcasts/theonelanceb-trading-podcast/episodes/16-years-of-swing-trading-lessons-in-12-minutes) | gap, capacity |
| [99% of Traders Don't Know How to Trade with the Trend](https://www.youtube.com/watch?v=ZOHG-OnQuos) | [Creator companion article](https://theonelanceb.com/blog/99-of-traders-dont-know-how-to-trade-with-the-trend/) | pivots |
| [Stop Trading in No Man’s Land If You Want to Be Profitable](https://www.youtube.com/watch?v=fCp6CRu6E5Y) | [Creator companion article](https://theonelanceb.com/blog/stop-trading-in-no-mans-land-if-you-want-to-become-profitable/) | range |
| [Why Your Support & Resistance Lines Don’t Work](https://www.youtube.com/watch?v=UAlhNPmvB14) | [Creator companion episode transcript excerpt](https://podscan.fm/podcasts/theonelanceb-trading-podcast/episodes/why-your-support-amp-resistance-lines-dont-work-100m-trader-explains) | level, porous |
| [This Right Side of the V Trading Strategy Made Me Millions](https://www.youtube.com/watch?v=wtQIj6Apiq0) | [Creator description, chapters and companion article](https://theonelanceb.com/blog/the-right-side-of-the-v-a-game-changer-for-traders/) | turn, acceleration |
| [Can You Pass This Technical Analysis Test? (How to Know Which Charts Are Worth Trading)](https://www.youtube.com/watch?v=9SgNXrWTefY) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=9SgNXrWTefY) | comparison, shortstructure |
| [I Only Trade Stocks That Meet This Criteria](https://www.youtube.com/watch?v=7FbTZZNljSo) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=7FbTZZNljSo) | watchlist, participation |
| [The Anchored VWAP Edge Most Traders Never Discover](https://www.youtube.com/watch?v=D2P-0xh6aEM) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=D2P-0xh6aEM) | avwap |
| [Reacting to Kristjan Qullamaggie’s Moving Average Trading Strategy](https://www.youtube.com/watch?v=H01JbbEY7ac) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=H01JbbEY7ac) | averages |
| [How to Set Up Your Trading Charts Like a Pro (Beginner’s Guide)](https://www.youtube.com/watch?v=9WqaZ_4Cld0) | [Creator description and available companion transcript](https://podscan.fm/podcasts/theonelanceb-trading-podcast/episodes/how-to-set-up-your-trading-charts-like-a-pro-beginners-guide-1) | horizon |
| [3 ORB Trading Strategies That Made Me Millions](https://www.youtube.com/watch?v=QmPUp9ISuDw) | [Creator syndicated description and chapters](https://podscan.fm/podcasts/theonelanceb-trading-podcast/episodes/3-orb-trading-strategies-that-made-me-millions) | opening, exhaustiongap |
| [The 3 Scalping Trading Strategies That Made Me Millions](https://www.youtube.com/watch?v=2DXQqwKSwJE) | [Creator companion article](https://theonelanceb.com/blog/3-scalping-strategies-every-trader-should-know/) | tape |
| [15 Years of Trading Risk Management in 20 Minutes](https://www.youtube.com/watch?v=gb7nNveNBjg) | [Creator syndicated chapter notes](https://podcasts.apple.com/za/podcast/15-years-of-trading-risk-management-in-20-minutes/id1888279300?i=1000757721623) | limit, shortcost, stopfill |
| [52 Minute Risk Management Masterclass from a $100,000,000 Trader](https://www.youtube.com/watch?v=hC4g7qY6UcQ) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=hC4g7qY6UcQ) | ruin, kelly, scaling |
| [How to Handle Trading Drawdowns (Step-by-step process)](https://www.youtube.com/watch?v=o7DfwJTC_Ow) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=o7DfwJTC_Ow) | drawdown |
| [Copy My Trading Report Card That Made Me $100 Million](https://www.youtube.com/watch?v=vKy6Q9hwon4) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=vKy6Q9hwon4) | audit |
| [Learn from Your Losing Trades with My 3-Step Review System](https://www.youtube.com/watch?v=ABzXM-9LonM) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=ABzXM-9LonM) | lossreview |
| [This Risk Management Trading Strategy Saved My Career](https://www.youtube.com/watch?v=9Mr2dSi-EEc) | [Creator description and published chapter headings](https://www.youtube.com/watch?v=9Mr2dSi-EEc) | capital |
