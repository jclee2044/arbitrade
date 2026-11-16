"""Run all-timeframe browser SmokeTest with isolated data and service cleanup."""
import argparse
from pathlib import Path
from scripts.history_smoke import verify

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-provider-history'))
    verify(parser.parse_args().output.resolve(), 'scripts.provider_history_fixture:app',
           'scripts/provider_history_smoke.mjs', 'constructed daily and intraday provider prices')
