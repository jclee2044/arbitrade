"""Verify saved Yahoo counters -> API/WebSocket -> chart, without source writes."""
import argparse
from pathlib import Path
from scripts.history_smoke import verify

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/arbitrade-recorded-volume'))
    verify(parser.parse_args().output.resolve(), 'scripts.recorded_volume_fixture:app',
           'scripts/recorded_volume_smoke.mjs', 'actual saved Yahoo; frozen clock and disposable database copy')
