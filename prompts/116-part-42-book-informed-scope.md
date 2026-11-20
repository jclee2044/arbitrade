this is 4.2. what can we pull from the books and add into the app with this next version in mind.

## Part 4.2 — Indicators, Simulated Trading, and Backtesting

**Outcome:** a workstation that derives signals and measures simulated trading outcomes.

- **Indicators.** Display two simple moving averages of different lengths and their crossover. EMA, MACD, RSI, and other indicator types are optional.
- **Simulated trading and accounting.** Apply the SMA crossover strategy in a simulated account. Track orders and fills, cash, positions, and realized and unrealized profit or loss. Make the account state and trade history understandable, and document the assumptions used to simulate execution and calculate results.
- **Backtesting.** Evaluate the strategy on historical data using only information available at each decision time. Show the resulting trades and account performance, and explain what the results establish and what they leave uncertain.

Verify the moving averages and crossover against a trusted reference, compare batch and incremental calculations, and explain how unfinished candles are handled. Check simulated accounting against known examples. Keep browser tests and run automated checks on pushes using GitHub Actions.

## Submission

Upload only `report.md` to Canvas for Assignment 4, Part 2. The report must include:

- **Report.** Summarize what was completed, key design decisions, verification results, and remaining limitations. Include links to supporting documents and evidence.
- **GitHub repository.** Include the repository URL and the commit identifying the submitted version.
- **Short video.** Include an accessible link to one video lasting **30 seconds to 1 minute**, demonstrating the working application features required for that part.

**Do not upload source-code files or ZIP archives to Canvas.** Keep source code in the linked GitHub repository. Ensure that the instructor can access both the repository and the video.

Follow the requirements in the [Assignment 4 overview](https://psu.instructure.com/courses/2484533/pages/assignment-4-overview-live-market-workstation), Section 6: Submission.

This part is worth 100 points. Assignment 4 has four equally weighted components: three submissions and one live in-class presentation.
