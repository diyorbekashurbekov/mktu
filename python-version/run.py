"""Run from the profitability-ai directory: python run.py"""
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from profitai.server import main

if __name__ == "__main__":
    main()
