"""Run the multi-ticker paper trading browser and SQLite SmokeTest."""

import argparse
from pathlib import Path

from scripts.history_smoke import verify


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-multi-ticker-paper'))
    verify(parser.parse_args().output.resolve(), 'scripts.multi_ticker_paper_fixture:app',
           'scripts/multi_ticker_paper_smoke.mjs', 'constructed Yahoo transport and disposable paper ledger')
