"""Test-only worker for P07-B hard termination. Generates no external data."""
from pathlib import Path
import argparse
import processed_integration as subject
from joint42_selftest import FixturePlanner

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('work',type=Path)
    a=ap.parse_args()
    # The parent kills this process after the sealed OWNER.json appears. It may
    # be in HE/AUTO or later; any hard death must leave only owned recoverables.
    subject.run_file(a.source,a.work,planner=FixturePlanner('tail'),enable_lab=True)

if __name__=='__main__':main()
