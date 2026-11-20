"""Confirm DEV timing qualification on a new independent held-out partition."""
import argparse
import json
from pathlib import Path
import correction

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    correction.PROTOCOL = json.loads(Path(__file__).with_name('timing_protocol.json').read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    correction.evaluate(args.out, args.index, correction.PROTOCOL['test_partition'])
