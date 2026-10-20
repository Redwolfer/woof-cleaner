"""PyInstaller entry point for WoofCleaner.exe (windowed)."""
from woofcleaner.cli import main

if __name__ == "__main__":
    main(["gui"])
