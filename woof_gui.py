"""PyInstaller entry point for WoofCleaner.exe (windowed). Arguments are passed through (scheduled cleans use them)."""
import sys

from woofcleaner.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["gui"]))
