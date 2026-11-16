"""Unit tests for Markdown parsing, frontmatter, TOC and post-processing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import deep_merge, validate_settings
from app.markdown_engine import (
    MarkdownError,
    apply_frontmatter,
    build_toc,
    inject_pagebreaks,
    parse_markdown,
    slugify,
    split_frontmatter,
)


def render(text: str, base_dir: Path | None = None, **settings_overrides):
    settings = validate_settings(deep_merge({}, settings_overrides))
    return parse_markdown(text, settings, base_dir=base_dir)


def test_slugify_handles_italian_accents():
    assert slugify("Perché un’applicazione locale") == "perché-unapplicazione-locale"
    assert slugify("H1 — Titolo!") == "h1-titolo"
    assert slugify("!!!") == "sezione"


def test_split_frontmatter_parses_yaml_and_dates():
    meta, body = split_frontmatter("---\ntitle: Ciao\ndate: 2026-01-02\ntoc: true\n---\n# Titolo\n")
    assert meta["title"] == "Ciao"
    assert meta["date"] == "2026-01-02"
    assert meta["toc"] is True
    assert body == "# Titolo\n"


def test_invalid_yaml_raises_clear_error():
    with pytest.raises(MarkdownError, match="YAML frontmatter non valido"):
        split_frontmatter("---\ntitle: [non chiuso\n---\ntesto\n")


def test_non_mapping_frontmatter_is_rejected():
    with pytest.raises(MarkdownError, match="mappa"):
        split_frontmatter("---\n- a\n- b\n---\ntesto\n")


def test_apply_frontmatter_string_header_replaces_all_slots():
    settings = validate_settings(
        {
            "headerFooter": {
                "headerLeft": "Sinistra",
                "headerCenter": "Centro",
                "headerRight": "Destra",
                "footerLeft": "Sinistra",
                "footerCenter": "Centro",
                "footerRight": "Destra",
            }
        }
    )
    result = apply_frontmatter(settings, {"header": "Solo titolo", "footer": "Solo pagina"})
    assert result["headerFooter"]["headerLeft"] == ""
    assert result["headerFooter"]["headerCenter"] == "Solo titolo"
    assert result["headerFooter"]["headerRight"] == ""
    assert result["headerFooter"]["footerLeft"] == ""
    assert result["headerFooter"]["footerCenter"] == "Solo pagina"
    assert result["headerFooter"]["footerRight"] == ""


def test_apply_frontmatter_merges_document_header_footer():
    settings = validate_settings({})
    result = apply_frontmatter(
        settings,
        {
            "title": "Titolo",
            "author": "Autore",
            "toc": True,
            "toc_depth": 2,
            "header": "{title}",
            "footer": {"left": "{author}", "center": "{page}", "right": "{filename}"},
        },
    )
    assert result["document"]["title"] == "Titolo"
    assert result["document"]["toc"] is True
    assert result["document"]["tocDepth"] == 2
    assert result["headerFooter"]["headerCenter"] == "{title}"
    assert result["headerFooter"]["footerCenter"] == "{page}"
    assert result["headerFooter"]["footerLeft"] == "{author}"
    assert result["headerFooter"]["footerRight"] == "{filename}"


def test_headings_ids_and_toc_links():
    rendered = render(
        "# Introduzione\n\n## Perché è importante\n\n### Dettagli\n\n#### Troppo profondo\n",
        document={"toc": True, "tocDepth": 3, "tocTitle": "Indice"},
    )
    slugs = [heading.slug for heading in rendered.headings]
    assert slugs == ["introduzione", "perché-è-importante", "dettagli", "troppo-profondo"]
    assert '<h1 id="introduzione"' in rendered.body_html
    assert '<a href="#perché-è-importante">' in rendered.toc_html
    assert "Troppo profondo" not in rendered.toc_html
    assert 'class="toc-page"' in rendered.toc_html


def test_heading_explicit_id_and_duplicate_slugs():
    rendered = render("# Titolo {#custom-id}\n\n# Titolo\n\n# Titolo\n")
    assert rendered.headings[0].slug == "custom-id"
    assert rendered.headings[1].slug == "titolo"
    assert rendered.headings[2].slug == "titolo-1"
    assert 'href="#custom-id"' not in rendered.toc_html  # TOC disabled by default


def test_heading_numbering_is_hierarchical():
    rendered = render(
        "# Uno\n\n## Uno.A\n\n## Uno.B\n\n# Due\n\n## Due.A\n",
        document={"numberHeadings": True},
    )
    numbers = [heading.number for heading in rendered.headings]
    assert numbers == ["1", "1.1", "1.2", "2", "2.1"]
    assert '<span class="hnum">1.1.</span>' in rendered.body_html


def test_tables_alignments_and_numbering():
    rendered = render(
        "| Sinistra | Centro | Destra |\n|:---------|:------:|-------:|\n| a | b | c |\n",
        document={"numberTables": True},
    )
    html = rendered.body_html
    assert 'class="doc-table"' in html
    assert "Tabella 1" in html
    assert "text-align:left" in html
    assert "text-align:center" in html
    assert "text-align:right" in html


def test_tasklists_render_safe_checkboxes():
    rendered = render("- [x] Fatto\n- [ ] Da fare\n")
    html = rendered.body_html
    assert "task-checkbox is-checked" in html
    assert "task-checkbox" in html
    assert "<input" not in html
    assert 'class="contains-task-list"' in html


def test_code_highlighting_and_line_numbers():
    rendered = render("```python linenums\nprint('ciao')\nprint('<b>')\n```\n")
    html = rendered.body_html
    assert "code-block has-line-numbers" in html
    assert "code-gutter" in html
    assert "python" in html
    assert "&lt;b&gt;" in html
    assert "language-python" in html


def test_inline_code_link_image_and_strikethrough():
    rendered = render(
        "`inline` e [link](https://example.com) e ~~barrato~~ e ![alt](missing.png)\n"
    )
    html = rendered.body_html
    assert "<code>inline</code>" in html
    assert 'href="https://example.com"' in html
    assert "<s>barrato</s>" in html
    assert "doc-image" in html
    assert any("missing.png" in warning["message"] for warning in rendered.warnings)


def test_local_image_resolves_to_file_uri(tmp_path: Path):
    image = tmp_path / "pic.svg"
    image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>', encoding="utf-8")
    rendered = render("![Alt](pic.svg)\n", base_dir=tmp_path)
    assert image.as_uri() in rendered.body_html
    assert rendered.warnings == []


def test_missing_image_uses_placeholder_and_warning(tmp_path: Path):
    rendered = render("![Assente](non-esiste.png)\n", base_dir=tmp_path)
    assert "data:image/svg+xml;base64," in rendered.body_html
    assert any("non-esiste.png" in warning["message"] for warning in rendered.warnings)


def test_figure_and_caption_numbering(tmp_path: Path):
    image = tmp_path / "pic.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    rendered = render("![Didascalia](pic.png)\n", base_dir=tmp_path, document={"numberFigures": True})
    html = rendered.body_html
    assert 'class="doc-figure"' in html
    assert "Figura 1 — Didascalia" in html
    assert 'class="figure-caption"' in html


def test_footnotes_are_rendered_and_linked():
    rendered = render("Testo con nota[^1].\n\n[^1]: Contenuto della nota.\n")
    html = rendered.body_html
    assert 'class="footnote-ref"' in html or "footnote-ref" in html
    assert 'id="fn1"' in html
    assert "Contenuto della nota" in html
    assert 'href="#fn1"' in html


def test_blockquote_and_pagebreak_comment():
    rendered = render("> Citazione\n\n<!-- pagebreak -->\n\n# Dopo\n")
    html = rendered.body_html
    assert "<blockquote>" in html
    assert 'class="page-break"' in html
    assert "<!-- pagebreak -->" not in html


def test_pagebreak_backslash_and_code_fence_preservation():
    text = "Prima\n\n\\newpage\n\n```\n\\newpage\n<!-- pagebreak -->\n```\n\nDopo\n"
    prepared = inject_pagebreaks(text)
    assert prepared.count('class="page-break"') == 1
    assert "\\newpage" in prepared  # kept inside the fence
    assert "<!-- pagebreak -->" in prepared


def test_toc_disabled_returns_empty():
    rendered = render("# Solo titolo\n")
    assert rendered.toc_html == ""


def test_build_toc_nested_structure():
    parsed = render(
        "# A\n\n## B\n\n### C\n\n## D\n",
        document={"toc": True, "tocDepth": 3, "numberHeadings": True},
    )
    signature = build_toc(parsed.headings, validate_settings({"document": {"toc": True, "tocDepth": 3}}))
    assert signature.count("<ul>") >= 3
    assert "toc-level-1" in signature
    assert "toc-level-3" in signature


def test_emoji_and_special_characters_survive():
    rendered = render("Emoji 😀 🚀 e caratteri < > & con accenti è à ù.\n")
    assert "😀" in rendered.body_html
    assert "&lt; &gt; &amp;" in rendered.body_html


def test_empty_markdown_is_rejected():
    with pytest.raises(MarkdownError, match="vuoto"):
        parse_markdown("   \n\n", validate_settings({}))


def test_frontmatter_is_not_rendered_as_content():
    meta, body = split_frontmatter("---\ntitle: Solo frontmatter\n---\n\n# Contenuto\n")
    rendered = parse_markdown(body, validate_settings({}))
    assert "Solo frontmatter" not in rendered.body_html
    assert "Contenuto" in rendered.body_html


def test_latex_delimiter_normalisation_outside_code():
    from app.markdown_engine import normalize_latex_delimiters

    text = "Inline \\(a+b\\) e blocco:\n\n\\[\nx^2 + y^2 = z^2\n\\]\n\n```\n\\(non toccare\\)\n```\n"
    normalized = normalize_latex_delimiters(text)
    assert "$a+b$" in normalized
    assert "$$\nx^2 + y^2 = z^2\n$$" in normalized
    assert "\\(non toccare\\)" in normalized


def test_math_inline_and_block_render_with_katex():
    from app.rich_rendering import rich_available

    if not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    rendered = render("Inline $E = mc^2$ e blocco:\n\n$$\\frac{a}{b} = \\sqrt{c}$$\n")
    assert rendered.has_math is True
    assert 'class="math-inline"' in rendered.body_html
    assert 'class="katex"' in rendered.body_html
    assert 'class="math-block"' in rendered.body_html
    assert "katex-display" in rendered.body_html
    assert rendered.warnings == []
    assert "$$" not in rendered.body_html


def test_invalid_latex_falls_back_with_warning():
    from app.rich_rendering import rich_available

    if not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    rendered = render("Formula rotta: $\\notacommand{abc}$\n")
    assert "math-error-inline" in rendered.body_html
    assert rendered.warnings
    assert "LaTeX" in rendered.warnings[0]["message"]


def test_mermaid_fence_renders_to_inline_png():
    from app.rich_rendering import rich_available

    if not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    diagram = """flowchart LR
  A[Markdown] --> B[PDF]
  B --> C{Fine}
"""
    rendered = render(f"```mermaid\n{diagram}```\n")
    assert 'class="mermaid-figure"' in rendered.body_html
    assert "data:image/png;base64," in rendered.body_html
    assert "mermaid-error" not in rendered.body_html
    assert rendered.warnings == []


def test_invalid_mermaid_falls_back_with_warning():
    from app.rich_rendering import rich_available

    if not rich_available():
        pytest.skip("Chromium/Playwright non disponibile")
    rendered = render("```mermaid\nquesto non è un diagramma valido\n```\n")
    assert 'class="mermaid-error"' in rendered.body_html
    assert rendered.warnings
    assert "Mermaid" in rendered.warnings[0]["message"]


def test_mermaid_and_math_inside_plain_code_are_not_rendered():
    rendered = render("```text\n$E = mc^2$\n```\n\n```text\nflowchart LR\n A-->B\n```\n")
    assert "katex" not in rendered.body_html
    assert "mermaid-figure" not in rendered.body_html
    assert rendered.has_math is False
