"""Job-item identity: the store's primary-key derivation, pinned.

The formula is the proposal's contract (Identifiers, 2026-07-21; revised
by ADR-0003 to include the environment, since jobs and their server-side
ids are per-environment):

    source_hash  = sha256(resolved absolute path)
    content_hash = sha256(document bytes)
    params_hash  = sha256(canonical JSON params)
    job_item_id  = sha256(verb ":" environment ":" source_hash
                          ":" content_hash ":" params_hash)[:16]

    url_hash     = sha256(URL string)          # no content component
    job_item_id  = sha256(verb ":" environment ":" url_hash
                          ":" params_hash)[:16]

These tests recompute ids from the documented formula with nothing but
hashlib — a refactor that changes any component silently re-keys every
store on every machine, so the derivation is pinned byte-for-byte.
"""

from __future__ import annotations

import hashlib
import json

from ade_cli import store

PARAMS = {"model": "dpt-3-pro-latest", "options": {"pages": [1, 3]}, "tier": "priority"}
ENV = "production"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_local_id_matches_the_documented_formula(tmp_path):
    doc = tmp_path / "invoice.pdf"
    doc.write_bytes(b"%PDF fake bytes")

    canonical = json.dumps(
        PARAMS, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    expected = _sha(
        "parse:production:"
        + _sha(str(doc.resolve()))
        + ":"
        + hashlib.sha256(b"%PDF fake bytes").hexdigest()
        + ":"
        + _sha(canonical)
    )[:16]

    identity = store.local_identity(doc, b"%PDF fake bytes")
    assert store.derive_id("parse", ENV, identity, PARAMS) == expected


def test_url_id_matches_the_documented_formula_with_no_content_component():
    url = "https://example.com/doc.pdf"
    canonical = json.dumps(
        PARAMS, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    expected = _sha("parse:production:" + _sha(url) + ":" + _sha(canonical))[:16]

    assert store.derive_id("parse", ENV, store.url_identity(url), PARAMS) == expected


def test_same_invocation_always_yields_the_same_id(tmp_path):
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"same bytes")

    first = store.derive_id(
        "parse", ENV, store.local_identity(doc, b"same bytes"), PARAMS
    )
    second = store.derive_id(
        "parse", ENV, store.local_identity(doc, b"same bytes"), PARAMS
    )

    assert first == second
    assert len(first) == store.JOB_ITEM_ID_HEX_CHARS


def test_params_hash_is_canonical_key_order_never_matters(tmp_path):
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"bytes")
    identity = store.local_identity(doc, b"bytes")

    shuffled = {"tier": "priority", "options": {"pages": [1, 3]}, "model": "dpt-3-pro-latest"}

    assert store.derive_id("parse", ENV, identity, PARAMS) == store.derive_id(
        "parse", ENV, identity, shuffled
    )


def test_any_component_differing_mints_a_sibling_id(tmp_path):
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"bytes")
    other_path = tmp_path / "b.pdf"
    other_path.write_bytes(b"bytes")
    base = store.derive_id("parse", ENV, store.local_identity(doc, b"bytes"), PARAMS)

    ids = {
        base,
        # verb: parse and extract ids never collide
        store.derive_id("extract", ENV, store.local_identity(doc, b"bytes"), PARAMS),
        # environment: a staging run never serves a production request
        store.derive_id("parse", "staging", store.local_identity(doc, b"bytes"), PARAMS),
        # source path: moving a file changes identity (accepted consequence)
        store.derive_id("parse", ENV, store.local_identity(other_path, b"bytes"), PARAMS),
        # content: an edited file is a different invocation
        store.derive_id("parse", ENV, store.local_identity(doc, b"other"), PARAMS),
        # params: variants are siblings, never replacements
        store.derive_id(
            "parse", ENV, store.local_identity(doc, b"bytes"), {**PARAMS, "tier": "standard"}
        ),
    }

    assert len(ids) == 6


def test_url_identity_keys_on_the_url_alone():
    # The CLI never sees a URL source's bytes before submit: identity is the
    # URL x params, so remote drift dedups against the stored item by design.
    a = store.derive_id("parse", ENV, store.url_identity("https://x.test/a"), PARAMS)
    b = store.derive_id("parse", ENV, store.url_identity("https://x.test/b"), PARAMS)

    assert a != b
