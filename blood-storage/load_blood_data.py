"""Compatibility entry point. Originals are preserved in data/raw/original_scripts."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from blood_response.cli import main

if __name__ == "__main__":
    main(["load", *sys.argv[1:]])
