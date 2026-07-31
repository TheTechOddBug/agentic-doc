"""Static invariants of the packaged HTML templates.

The mini markdown renderer is deliberately duplicated between
``view_template.html`` and ``crop_template.html`` — each artifact must stay
a self-contained single file (the snapshot design in view.py's module doc),
so there is no shared script to load. This test is the lockstep guard: the
two copies must stay byte-identical, so parity restored once (PR #44) can
never silently drift again.
"""

from importlib import resources

BEGIN = "/* ── shared-md-renderer:begin"
END = "/* ── shared-md-renderer:end ── */"


def shared_block(template_name: str) -> str:
    text = resources.files("ade_cli").joinpath(template_name).read_text("utf-8")
    assert text.count(BEGIN) == 1, f"{template_name}: begin marker missing or doubled"
    assert text.count(END) == 1, f"{template_name}: end marker missing or doubled"
    return text[text.index(BEGIN): text.index(END) + len(END)]


def test_markdown_renderer_is_byte_identical_in_both_templates():
    assert shared_block("view_template.html") == shared_block("crop_template.html")
