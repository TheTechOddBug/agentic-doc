"""Evidence: the local field→boxes join, computed offline with no API call.

Extraction spans and element spans index the *same* markdown string, so
each quoted field resolves through the elements projection to pages and
boxes: field → spans → overlapping elements → boxes. Persisted per
extraction as ``evidence.json`` — a derived index, recomputable from the
raw artifacts (``extract.json`` + ``parse.json``) alone.

Fields without spans split by whether there is anything to ground (F5):
an empty value (null, "") has no box an empty string could ground to and
is marked ``empty`` — expected, not alarming; a non-empty value with
null spans was synthesised rather than quoted and is marked
``ungroundable`` — the case that deserves attention. Neither is ever
dropped or guessed. Bring-your-own-markdown extractions have no parse to
join against and degrade to labeled spans-only records.
"""

from __future__ import annotations

from typing import Iterator

from . import elements, items
from .store import JobStore


def metadata_leaves(node: object, prefix: str = "") -> Iterator[tuple[str, dict]]:
    """Yield ``(field path, {value, ranges})`` leaves of an
    extraction_metadata tree, mirroring the extraction's shape."""
    if isinstance(node, dict):
        if "value" in node and "ranges" in node:
            yield prefix, node
            return
        for key, child in node.items():
            yield from metadata_leaves(child, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(node, list):
        for i, child in enumerate(node):
            yield from metadata_leaves(child, f"{prefix}[{i}]")


def build(
    extraction_metadata: dict,
    element_records: list[dict] | None,
    *,
    job_id: str,
    parse_job_id: str | None,
) -> dict:
    """The evidence document for one extraction.

    ``element_records`` must come from the parse generation the extraction
    ran against (its spans index that exact markdown); None means there is
    no grounding to join against and the fields stay spans-only — with the
    degradation and its cause stated in ``kind``/``reason``, never implied
    by silence.
    """
    doc = {
        # Generation stamps: the extract job that produced the spans and the
        # parse fingerprint they index. Readers serve a stored evidence.json
        # only while its job_id matches the extraction's commit record.
        "job_id": job_id,
        "parse_job_id": parse_job_id,
        "kind": "grounded" if element_records is not None else "spans_only",
        "fields": [
            _field_evidence(path, leaf, element_records)
            for path, leaf in metadata_leaves(extraction_metadata)
        ],
    }
    if element_records is None:
        # Two distinct degradations share the spans-only shape: a markdown
        # doc never had grounding; a replaced parse had it, but the raw
        # artifacts of that generation are gone (the stored evidence.json,
        # still true of the bytes it was computed from, is then the only
        # surviving join — this branch is its recompute fallback).
        doc["reason"] = "markdown_doc" if parse_job_id is None else "parse_replaced"
    return doc


def _field_evidence(path: str, leaf: dict, element_records: list[dict] | None) -> dict:
    if not leaf["ranges"]:
        # No spans. An empty value is empty by nature — there is no box an
        # empty string could ground to (blank cells, absent optionals);
        # only a non-empty value without spans was synthesised rather than
        # quoted, which is the case that deserves attention (F5). False/0
        # are real values, not empty.
        if leaf["value"] is None or leaf["value"] == "":
            return {"field": path, "value": leaf["value"], "empty": True}
        return {"field": path, "value": leaf["value"], "ungroundable": True}
    spans = [[r["start"], r["end"]] for r in leaf["ranges"]]
    record = {"field": path, "value": leaf["value"], "spans": spans}
    if element_records is None:
        return record
    # A span hits every element whose span it overlaps (non-empty
    # intersection) — a value crossing element boundaries cites all of
    # them, including containers like a table around its cells. Boxes are
    # element-level (finer atomic_grounding crops are the viewer's job).
    # A quoted span that overlaps nothing — zero-length, or landing in
    # inter-element gaps like the doc_id trailer — keeps its empty lists:
    # explicit "no overlapping elements", distinct from ungroundable.
    hits = [
        el
        for el in element_records
        if any(el["span"][0] < end and start < el["span"][1] for start, end in spans)
    ]
    record["element_ids"] = [el["id"] for el in hits]
    record["pages"] = sorted({el["page"] for el in hits})
    record["boxes"] = [{"page": el["page"], "box": el["box"]} for el in hits]
    return record


def for_extraction(store: JobStore, item_id: str, meta: dict, response: dict) -> dict:
    """Evidence for an already-read completed extract item ``(meta,
    response)``.

    Serves the stored ``evidence.json`` only while its job_id stamp matches
    the extraction's commit record; otherwise recomputes in memory from the
    raw artifacts — resolving the referenced parse item through
    ``parse/ref.json``. The join runs only against the parse generation the
    extraction recorded — after a forced re-parse (stale extraction) with no
    stored evidence, the result honestly degrades to spans-only rather than
    joining spans into markdown they never indexed. Raw is truth, derived is
    disposable; this never writes.
    """
    stored = store.read_json(item_id, "evidence.json")
    if stored is not None and stored.get("job_id") == meta.get("job_id"):
        return stored
    parse_job_id = (meta.get("params") or {}).get("parse_job_id")
    element_records = None
    if parse_job_id is not None:
        ref = items.parse_ref(store, item_id) or {}
        parse_item_id = ref.get("job_item_id")
        if parse_item_id is not None:
            live_parse = items.live_parse(store, parse_item_id)
            if live_parse is not None and live_parse[0].get("job_id") == parse_job_id:
                element_records = elements.live_elements(store, parse_item_id)
    return build(
        # Defensive: a malformed or older on-disk extract.json missing the
        # key degrades to zero fields (metadata_leaves yields nothing on a
        # non-dict), never a KeyError while building the read model.
        response.get("extraction_metadata") or {},
        element_records,
        job_id=meta["job_id"],
        parse_job_id=parse_job_id,
    )
