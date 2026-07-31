"""Parse-job fixtures derived from the OpenAPI schemas in openapi.json:
ParseResponse (markdown + metadata + structure tree) and the
GET /v2/parse/jobs/{job_id} poll envelope."""

from __future__ import annotations

MODEL_VERSION = "dpt-3-pro-20260710"
JOB_ID = "job-0001"

# The server ends parse markdown with a doc_id trailer that extract reads.
MARKDOWN = "# Invoice\n\nTotal: €42\n\n<!-- doc_id=srv-doc-77aa00 -->\n"


def parse_response(
    *,
    markdown: str = MARKDOWN,
    job_id: str = JOB_ID,
    model_version: str = MODEL_VERSION,
    page_count: int = 1,
    failed_pages: list[int] | None = None,
    service_tier: str = "priority",
    total_credits: float = 2.5,
) -> dict:
    end = len(markdown)
    grounding = {
        "page": 1,
        "range": {"start": 0, "end": end},
        "box": {"xmin": 0.1, "ymin": 0.1, "xmax": 0.9, "ymax": 0.9},
    }
    element = {
        "type": "text",
        "id": "text-0",
        "grounding": grounding,
        "atomic_grounding": [grounding],
    }
    return {
        "markdown": markdown,
        "metadata": {
            "job_id": job_id,
            "model_version": model_version,
            "page_count": page_count,
            "output_markdown_chars": end,
            "range_units": "unicode_codepoints",
            "openapi_spec": "https://api.ade.landing.ai/openapi.json",
            "failed_pages": list(failed_pages or []),
            "duration_ms": 1234,
            "billing": {"service_tier": service_tier, "total_credits": total_credits},
        },
        "structure": {
            "type": "document",
            "children": [
                {
                    "type": "page",
                    "grounding": {
                        "page": 1,
                        "range": {"start": 0, "end": end},
                        "box": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0},
                    },
                    "status": "ok",
                    "children": [element],
                }
            ],
        },
    }


def rich_parse_response(*, job_id: str = JOB_ID) -> dict:
    """A two-page response exercising every shape the elements projection
    flattens: text, a table with `table_cell` children (row/col/spans), a
    figure — with markdown built piecewise so every range is exact.
    """
    pieces: list[str] = []

    def put(text: str) -> tuple[int, int]:
        start = sum(len(p) for p in pieces)
        pieces.append(text)
        return start, start + len(text)

    def box(i: int) -> dict:
        # Distinct per element so tests can tell whose box came through.
        return {"xmin": 0.01 * i, "ymin": 0.02 * i, "xmax": 0.5 + 0.01 * i, "ymax": 0.5 + 0.02 * i}

    def grounding(page: int, span: tuple[int, int], i: int) -> dict:
        return {
            "page": page,
            "range": {"start": span[0], "end": span[1]},
            "box": box(i),
        }

    def leaf(type_: str, id_: str, page: int, span: tuple[int, int], i: int, **extra) -> dict:
        g = grounding(page, span, i)
        atomic = [] if type_ == "table_cell" else [g]
        return {"type": type_, "id": id_, "grounding": g, "atomic_grounding": atomic, **extra}

    # Page 1: a heading and a 2x2 table whose cell ranges nest in the table's.
    heading = put("# Invoice\n\n")
    table_start = sum(len(p) for p in pieces)
    cells = []
    for row, (left, right) in enumerate([("Qty", "Price"), ("2", "€21")]):
        put("| ")
        for col, cell_text in enumerate((left, right)):
            if col:
                put(" | ")
            span = put(cell_text)
            cells.append(
                leaf(
                    "table_cell",
                    f"table_cell-{row * 2 + col}",
                    1,
                    span,
                    3 + row * 2 + col,
                    row=row,
                    col=col,
                    colspan=1,
                    rowspan=1,
                )
            )
        put(" |\n")
    table_span = (table_start, sum(len(p) for p in pieces))
    put("\n")
    table = {
        "type": "table",
        "id": "table-0",
        "grounding": grounding(1, table_span, 2),
        "children": cells,
    }
    page1_end = sum(len(p) for p in pieces)

    # Page 2: a text total and a figure.
    total = put("Total: €42\n\n")
    figure = put("Fig 1\n")
    page2_end = sum(len(p) for p in pieces)
    put("\n<!-- doc_id=srv-doc-77aa00 -->\n")

    markdown = "".join(pieces)
    data = parse_response(markdown=markdown, job_id=job_id, page_count=2)
    data["structure"] = {
        "type": "document",
        "children": [
            {
                "type": "page",
                "grounding": {
                    "page": 1,
                    "range": {"start": 0, "end": page1_end},
                    "box": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0},
                },
                "status": "ok",
                "children": [
                    leaf("text", "text-0", 1, heading, 1),
                    table,
                ],
            },
            {
                "type": "page",
                "grounding": {
                    "page": 2,
                    "range": {"start": page1_end, "end": page2_end},
                    "box": {"xmin": 0.0, "ymin": 0.0, "xmax": 1.0, "ymax": 1.0},
                },
                "status": "ok",
                "children": [
                    leaf("text", "text-1", 2, total, 7),
                    leaf("figure", "figure-0", 2, figure, 8),
                ],
            },
        ],
    }
    return data


def job_payload(
    status: str,
    *,
    job_id: str = JOB_ID,
    result: dict | None = None,
    failure_reason: str | None = None,
    progress: float = 0.0,
) -> dict:
    payload = {
        "job_id": job_id,
        "status": status,
        "created_at": "2026-07-15T00:00:00+00:00",
        "progress": progress,
        "result": result,
        "output_url": None,
        "error": (
            {"code": "parse_failed", "message": failure_reason}
            if failure_reason
            else None
        ),
    }
    if status in ("completed", "failed", "cancelled"):
        payload["completed_at"] = "2026-07-15T00:01:00+00:00"
    return payload


def completed_job(data: dict | None = None, *, job_id: str = JOB_ID) -> dict:
    data = data or parse_response(job_id=job_id)
    return job_payload("completed", job_id=job_id, result=data, progress=1.0)
