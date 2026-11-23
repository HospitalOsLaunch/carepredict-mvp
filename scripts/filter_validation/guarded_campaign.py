"""Evaluate the guarded estimator using the otherwise unchanged V3 harness."""
import argparse
import json
from pathlib import Path
import correction
from guarded_filter import posterior

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    correction.PROTOCOL = json.loads(Path(__file__).with_name('guarded_protocol.json').read_text())
    # Explicit estimator substitution. Calibration and every policy use this
    # selected profile; original V3 commands retain their original estimator.
    correction.posterior = posterior
    args.out.mkdir(parents=True, exist_ok=True)
    correction.evaluate(args.out, args.index, correction.PROTOCOL['test_partition'])
