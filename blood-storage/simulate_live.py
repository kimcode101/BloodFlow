"""Offline by default; --database explicitly opts into PostgreSQL mutation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blood_response.cli import main

if __name__ == "__main__":
    try:
        main(["simulate", *sys.argv[1:]])
    except KeyboardInterrupt:
        print("Stopped.")
