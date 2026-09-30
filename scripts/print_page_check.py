"""Export a printable page to PDF with headless Chrome and report page count and last line of each page.

Usage: python3 scripts/print_page_check.py <url> [expected_pages]
Exit 0: PDF produced and (if given) the page count matches.
Exit 1: PDF produced but the page count differs.
Exit 2: could not produce or read a PDF (bad arguments, Chrome missing/failed, unreadable PDF).
Needs pypdf (prototype venv).  Read-only: it only opens the URL.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def die(message: str, code: int = 2):
    print(f"FAIL: {message}")
    sys.exit(code)


if len(sys.argv) not in (2, 3) or not sys.argv[1].startswith(("http://", "https://")):
    die("usage: print_page_check.py <http(s) url> [expected_pages]")
url = sys.argv[1]
try:
    expected = int(sys.argv[2]) if len(sys.argv) == 3 else None
    if expected is not None and expected < 1:
        raise ValueError
except ValueError:
    die("expected_pages must be a positive integer")
if not os.path.exists(CHROME):
    die(f"Chrome not found at {CHROME}")
try:
    from pypdf import PdfReader
except ImportError:
    die("pypdf is not installed (use prototype/.venv/bin/python)")

work = tempfile.mkdtemp(prefix="printcheck.")
pdf = os.path.join(work, "out.pdf")
proc = None
try:
    proc = subprocess.Popen(
        [CHROME, "--headless=new", "--disable-gpu", "--no-proxy-server", f"--user-data-dir={work}/prof",
         "--no-pdf-header-footer", f"--print-to-pdf={pdf}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "NO_PROXY": "127.0.0.1,localhost"})
    # Wait until Chrome exits, or the file exists and its size has stopped changing (Chrome may linger).
    last, stable, deadline = -1, 0, time.time() + 40
    while time.time() < deadline:
        size = os.path.getsize(pdf) if os.path.exists(pdf) else 0
        stable = stable + 1 if size > 0 and size == last else 0
        last = size
        if stable >= 3 or (proc.poll() is not None and size > 0):
            break
        if proc.poll() not in (None, 0) and size == 0:
            die(f"Chrome exited with code {proc.returncode} without producing a PDF")
        time.sleep(0.5)
    else:
        die("timed out waiting for the PDF")
    try:
        pages = PdfReader(pdf).pages
        lines = [(p.extract_text().strip().splitlines() or [""])[-1] for p in pages]
    except Exception as exc:  # truncated or corrupt PDF
        die(f"could not read the PDF ({type(exc).__name__}: {exc})")
finally:
    if proc is not None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        proc.wait()
    subprocess.run(["pkill", "-f", "--", f"user-data-dir={work}/prof"], check=False)
    shutil.rmtree(work, ignore_errors=True)

print(f"PDF pages={len(pages)} last_lines={lines}")
if expected is not None and len(pages) != expected:
    die(f"expected {expected} pages", 1)
