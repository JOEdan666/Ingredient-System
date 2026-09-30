"""Fail CI if concurrency tests were skipped or fewer than the documented count."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

EXPECTED = 15


def main(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    executed = sum(int(s.get("tests", 0)) - int(s.get("skipped", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    print(f"concurrency: executed={executed}, expected>={EXPECTED}, failed={failed}")
    if executed < EXPECTED or failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
