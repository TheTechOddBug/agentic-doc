"""``python -m ade_cli`` — the re-exec entry the background viewer builder
uses (subprocess can rely on it wherever the package is importable, which
the installed console script cannot promise)."""

from .main import app

app()
