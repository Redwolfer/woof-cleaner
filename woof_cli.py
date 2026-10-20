"""PyInstaller entry point for woof.exe (console). With no arguments it opens the GUI."""
import sys

from woofcleaner.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
