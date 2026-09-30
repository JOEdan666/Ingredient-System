"""Export a printable page to PDF with headless Chrome and report page count and last line of each page.

Usage: python3 scripts/print_page_check.py <url> [expected_pages]
Exit 0 when the PDF was produced (and the count matches, if given); 1 otherwise.
Needs pypdf (prototype venv).  Read-only: it only opens the URL.
"""
import os
import subprocess
import sys
import tempfile
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
url = sys.argv[1]
expected = int(sys.argv[2]) if len(sys.argv) > 2 else None
work = tempfile.mkdtemp(prefix="printcheck.")
pdf = os.path.join(work, "out.pdf")
proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--no-proxy-server", f"--user-data-dir={work}/prof",
                         "--no-pdf-header-footer", f"--print-to-pdf={pdf}", url],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "NO_PROXY": "127.0.0.1,localhost"})
try:
    for _ in range(60):
        if os.path.exists(pdf) and os.path.getsize(pdf) > 0:
            time.sleep(1)
            break
        time.sleep(0.5)
finally:
    proc.kill()
    subprocess.run(["pkill", "-f", "--", f"user-data-dir={work}/prof"], check=False)
if not os.path.exists(pdf):
    print("FAIL: no PDF produced")
    sys.exit(1)
from pypdf import PdfReader
pages = PdfReader(pdf).pages
lines = [(p.extract_text().strip().splitlines() or [""])[-1] for p in pages]
print(f"PDF pages={len(pages)} last_lines={lines}")
if expected is not None and len(pages) != expected:
    print(f"FAIL: expected {expected} pages")
    sys.exit(1)
