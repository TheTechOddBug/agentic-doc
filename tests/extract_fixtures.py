"""Extract-job fixtures derived from the OpenAPI schemas in openapi.json:
V2ExtractResult (extraction + extraction_metadata + metadata) and the
GET /v2/extract/jobs/{job_id} poll envelope (same shape as parse's).

``extraction_metadata`` mirrors ``extraction`` with leaf values replaced
by ``{value, ranges}`` objects; ``ranges`` are ``[start, end)`` code-point
offsets into the input markdown, ``null`` for synthesised (ungroundable)
values.
"""

from __future__ import annotations

from parse_fixtures import MARKDOWN, job_payload

EXTRACT_JOB_ID = "extract-0001"
EXTRACT_MODEL_VERSION = "extract-20260710"

# A schema with one quotable field (total: in the parse markdown) and one
# the model must synthesise (vendor: nowhere in the markdown).
SCHEMA = {
    "type": "object",
    "properties": {
        "total": {"type": "string", "description": "Invoice total"},
        "vendor": {"type": "string", "description": "Vendor name"},
    },
}


def extract_result(
    *,
    markdown: str = MARKDOWN,
    job_id: str = EXTRACT_JOB_ID,
    version: str = EXTRACT_MODEL_VERSION,
    extraction: dict | None = None,
    extraction_metadata: dict | None = None,
    service_tier: str = "priority",
    total_credits: float = 1.0,
    warnings: list | None = None,
    schema_violation_error: str | None = None,
) -> dict:
    if extraction is None:
        # "total" is quoted from the markdown (grounded ranges); "vendor"
        # is synthesised (null ranges ⇒ ungroundable).
        at = max(markdown.find("€42"), 0)
        extraction = {"total": "€42", "vendor": "Acme Corp"}
        extraction_metadata = {
            "total": {"value": "€42", "ranges": [{"start": at, "end": at + 3}]},
            "vendor": {"value": "Acme Corp", "ranges": None},
        }
    assert extraction_metadata is not None
    return {
        "extraction": extraction,
        "extraction_metadata": extraction_metadata,
        "markdown": markdown,  # echoed input
        # Both partial-success signals ride every poll body (a partial
        # extraction still polls as status=completed, HTTP 200):
        # schema_violation_error is set when strict=false and the model
        # could not extract some schema fields (fixtures model reality).
        "warnings": warnings or [],
        "schema_violation_error": schema_violation_error,
        "metadata": {
            "job_id": job_id,
            # The deployed wire uses model_version (like parse), not the
            # openapi.json snapshot's `version` — fixtures model reality.
            "model_version": version,
            "duration_ms": 512,
            "doc_id": "srv-doc-77aa00",  # read from the markdown trailer
            "range_units": "unicode_codepoints",
            # No top-level credit_usage: the deployed wire bills via
            # metadata.billing only (fixtures model reality; the legacy
            # credit_usage fallback is seeded directly where tested).
            "openapi_spec": "https://api.ade.landing.ai/openapi.json",
            "billing": {"service_tier": service_tier, "total_credits": total_credits},
        },
    }


def completed_extract_job(
    result: dict | None = None, *, job_id: str = EXTRACT_JOB_ID
) -> dict:
    return job_payload(
        "completed",
        job_id=job_id,
        result=result if result is not None else extract_result(job_id=job_id),
        progress=1.0,
    )
