"""Client identity: the User-Agent sent on every ADE API request.

Wire format (documented for the platform side in ``docs/user-agent.md``)::

    ade-cli/<version> (<os> <arch>) python/<major.minor> httpx/<version> command/<name>

This module builds the base (everything before ``command/``) and nowhere
else. Extra tokens append as further ``key/value`` pairs via
``user_agent(*extra)`` — the gateway adds ``command/<name>`` naming the
invoking CLI command; follow-ups (host-app) ride the same seam.
"""

from __future__ import annotations

import platform
import sys
from functools import cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _installed_version

import httpx


def _cli_version() -> str:
    # Frozen builds carry only the dist-info the build step explicitly
    # copies; identity must not be able to fail a request (issue #97), so a
    # missing record degrades to a placeholder instead of raising.
    try:
        return _installed_version("ade-cli")
    except PackageNotFoundError:
        return "unknown"


@cache
def _base() -> str:
    # Static for the life of the process; cached because polling hits this
    # once per request and importlib.metadata reads package metadata files.
    # httpx's version comes from the module, never importlib.metadata: the
    # frozen app bundles no dependency dist-info, and 0.1.3 crashed every
    # API request on that lookup (issue #97).
    return " ".join(
        (
            f"ade-cli/{_cli_version()}",
            f"({platform.system()} {platform.machine()})",
            f"python/{sys.version_info.major}.{sys.version_info.minor}",
            f"httpx/{httpx.__version__}",
        )
    )


def user_agent(*extra: tuple[str, str]) -> str:
    """The identity string, with any extra ``(key, value)`` tokens appended."""
    return " ".join((_base(), *(f"{key}/{value}" for key, value in extra)))
