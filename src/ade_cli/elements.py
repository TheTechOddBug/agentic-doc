"""The elements projection: the flat per-element view of a parse.

``parse.json`` (the raw ParseResponse) is ground truth; the projection
flattens its structure tree — pages, elements, table cells — into one
record per element in document order (page, then reading order; a table
immediately followed by its cells). Written at parse finalize as
``elements.json``, stamped with the generation's job_id, and always
recomputable from the raw response alone.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from . import items
from .store import JobStore


def project(response: dict) -> list[dict]:
    """Flatten a raw ParseResponse into element records.

    Each record carries the element's identity (``id``, ``type``), its
    place (``page``, ``span``, ``box``), its markdown slice (``text``),
    its fine-grained ``atomic_grounding`` when the response has one, cell
    position (``row``/``col``/``colspan``/``rowspan``) on table cells,
    and the cell ids (``cells``) on tables.
    """
    markdown = response["markdown"]
    records: list[dict] = []
    for page in response["structure"]["children"]:
        for element in page.get("children") or []:
            _flatten(element, markdown, records)
    return records


def _flatten(element: dict, markdown: str, records: list[dict]) -> None:
    grounding = element["grounding"]
    start, end = grounding["range"]["start"], grounding["range"]["end"]
    record = {
        "id": element["id"],
        "type": element["type"],
        "page": grounding["page"],
        "span": [start, end],
        # Ranges are Unicode code points (metadata.range_units), which is
        # exactly what Python string slicing counts.
        "text": markdown[start:end],
        "box": grounding["box"],
    }
    if element.get("atomic_grounding") is not None:
        record["atomic_grounding"] = element["atomic_grounding"]
    for key in ("row", "col", "colspan", "rowspan"):
        if element.get(key) is not None:
            record[key] = element[key]
    cells = element.get("children") or []
    if cells:
        record["cells"] = [cell["id"] for cell in cells]
    records.append(record)
    for cell in cells:
        _flatten(cell, markdown, records)


def select(
    records: list[dict],
    *,
    element_type: str | None = None,
    page: int | None = None,
    element_ids: Sequence[str] = (),
    query: str | None = None,
    pattern: re.Pattern[str] | None = None,
) -> list[dict]:
    """The one element filter, shared by ``find`` and ``crop``.

    Every criterion composes (AND) and nothing is ever ranked or
    reordered — the result stays in document order. Selecting elements is
    one concept, so it is one implementation: ``crop --type figure``
    means exactly what ``find --type figure`` means, by construction
    rather than by two filters agreeing.
    """

    def keep(record: dict) -> bool:
        if element_type is not None and record["type"] != element_type:
            return False
        if page is not None and record["page"] != page:
            return False
        if element_ids and record["id"] not in element_ids:
            return False
        if pattern is not None:
            return pattern.search(record["text"]) is not None
        if query is not None:
            return query.casefold() in record["text"].casefold()
        return True

    return [record for record in records if keep(record)]


def live_elements(store: JobStore, item_id: str) -> list[dict] | None:
    """The element records of the item's completed parse, or None when no
    generation-consistent parse is stored.

    Serves ``elements.json`` only while its job_id stamp matches the live
    generation; otherwise — projections written by older CLIs, or torn by
    a crash — it recomputes from the raw response in memory. Raw is truth,
    derived is disposable; this never writes.
    """
    live = items.live_parse(store, item_id)
    if live is None:
        return None
    meta, response = live
    stored = store.read_json(item_id, "elements.json")
    if stored is not None and stored.get("job_id") == meta.get("job_id"):
        return stored["elements"]
    return project(response)
