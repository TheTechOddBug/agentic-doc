"""PyInstaller entry point — the frozen twin of the `ade` console
script. PyInstaller needs a script file to trace imports from; keeping it
here (not in src/) keeps it out of the wheel."""

from ade_cli.main import app

app()
