"""Unit tests for CSS generation, page geometry and settings validation."""

from __future__ import annotations

import pytest

from app.config import (
    DEFAULT_SETTINGS,
    SettingsError,
    page_dimensions,
    sanitize_filename,
    validate_settings,
)
from app.styling import build_css, font_stack


def base_settings(**overrides):
    return validate_settings(overrides)


def test_page_size_and_margins_in_css():
    settings = base_settings(
        layout={
            "pageSize": "A4",
            "orientation": "portrait",
            "marginTop": 12,
            "marginBottom": 18,
            "marginLeft": 22,
            "marginRight": 14,
        }
    )
    css = build_css(settings, "relazione")
    assert "size: 210mm 297mm" in css
    assert "margin: 12mm 14mm 18mm 22mm" in css


def test_landscape_orientation_swaps_dimensions():
    settings = base_settings(layout={"pageSize": "A4", "orientation": "landscape"})
    assert page_dimensions(settings) == (297.0, 210.0)
    css = build_css(settings, "doc")
    assert "size: 297mm 210mm" in css


def test_custom_page_size_in_millimetres():
    settings = base_settings(
        layout={"pageSize": "custom", "customWidth": 120, "customHeight": 180, "orientation": "portrait"}
    )
    assert page_dimensions(settings) == (120.0, 180.0)
    assert "size: 120mm 180mm" in build_css(settings, "doc")


def test_fonts_sizes_scale_and_alignment():
    settings = base_settings(
        typography={
            "bodyFont": "DejaVu Serif",
            "headingFont": "DejaVu Sans",
            "monoFont": "DejaVu Sans Mono",
            "bodySize": 12,
            "h1Size": 30,
            "textAlign": "justify",
        },
        layout={"scale": 150},
    )
    css = build_css(settings, "doc")
    assert '"DejaVu Serif"' in css
    assert '"DejaVu Sans"' in css
    assert '"DejaVu Sans Mono"' in css
    assert "font-size: 18pt" in css  # 12pt * 150%
    assert "font-size: 45pt" in css  # 30pt * 150%
    assert "text-align: justify" in css


def test_theme_colors_are_emitted():
    settings = base_settings(
        theme={
            "name": "custom",
            "text": "#112233",
            "link": "#445566",
            "headings": "#778899",
            "border": "#aabbcc",
            "codeBg": "#ddeeff",
            "codeText": "#001122",
            "blockquoteBg": "#f0f0f0",
            "tableHeaderBg": "#ededed",
            "background": "#fafafa",
            "muted": "#999999",
        }
    )
    css = build_css(settings, "doc")
    for color in ("#112233", "#445566", "#778899", "#aabbcc", "#ddeeff", "#fafafa"):
        assert color in css


def test_header_footer_variables_and_counters():
    settings = base_settings(
        document={"title": "Il mio titolo", "author": "Anna", "date": "01/02/2026", "numberPages": True},
        headerFooter={
            "headerLeft": "{title}",
            "headerRight": "{author} — {date}",
            "footerCenter": "Pagina {page} di {pages} — {filename}",
        },
    )
    css = build_css(settings, "relazione-finale")
    assert "@top-left" in css
    assert "@top-right" in css
    assert "@bottom-center" in css
    assert '"Il mio titolo"' in css
    assert '"Anna"' in css
    assert "01/02/2026" in css
    assert "counter(page)" in css
    assert "counter(pages)" in css
    assert '"relazione-finale"' in css


def test_page_number_toggle_removes_default_footer():
    settings = base_settings(
        document={"numberPages": False},
        headerFooter={"footerCenter": "{page} / {pages}", "footerLeft": "", "footerRight": ""},
    )
    css = build_css(settings, "doc")
    assert "counter(page)" not in css
    assert "counter(pages)" not in css


def test_page_number_toggle_keeps_explicit_footer_when_requested():
    settings = base_settings(
        document={"numberPages": False},
        headerFooter={"footerCenter": "Foglio {page}"},
    )
    css = build_css(settings, "doc")
    assert "counter(page)" in css


def test_heading_orhan_and_break_inside_options():
    avoid = build_css(base_settings(layout={"avoidHeadingOrphans": True, "avoidBreakInside": True}), "doc")
    loose = build_css(base_settings(layout={"avoidHeadingOrphans": False, "avoidBreakInside": False}), "doc")
    assert "break-after: avoid-page" in avoid
    assert "break-inside: avoid" in avoid
    assert "break-after: avoid-page" not in loose


def test_cover_and_watermark_css():
    settings = base_settings(
        layout={
            "cover": {"enabled": True, "title": "Copertina", "subtitle": "Sub", "author": "A", "date": "D", "logo": ""},
            "watermark": {
                "enabled": True,
                "text": "RISERVATO",
                "opacity": 0.12,
                "rotation": -20,
                "position": "bottom-right",
                "color": "#ff0000",
            },
        }
    )
    css = build_css(settings, "doc")
    assert "@page cover" in css
    assert ".cover" in css
    assert ".watermark" in css
    assert "opacity: 0.120" in css
    assert "rotate(-20" in css or "-20deg" in css
    assert "#ff0000" in css


def test_cover_named_page_suppresses_margin_boxes():
    settings = base_settings(layout={"cover": {"enabled": True}})
    css = build_css(settings, "doc")
    assert "@page cover" in css
    for slot in ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"):
        assert f"@{slot} {{ content: none; }}" in css


def test_font_stack_keeps_emoji_out_of_family_list():
    stack = font_stack("DejaVu Serif", "serif")
    assert '"DejaVu Serif"' in stack
    assert stack.endswith("serif")
    # Explicitly listing the emoji font makes Pango render digits with it.
    assert "Noto Color Emoji" not in stack


@pytest.mark.parametrize("value", [7.9, 24.1, "abc", None])
def test_body_size_out_of_range_is_rejected(value):
    with pytest.raises(SettingsError, match="typography.bodySize"):
        validate_settings({"typography": {"bodySize": value}})


def test_body_size_bounds_are_accepted():
    assert validate_settings({"typography": {"bodySize": 8}})["typography"]["bodySize"] == 8
    assert validate_settings({"typography": {"bodySize": 24}})["typography"]["bodySize"] == 24


@pytest.mark.parametrize(
    "override,match",
    [
        ({"layout": {"orientation": "diagonal"}}, "layout.orientation"),
        ({"layout": {"pageSize": "A0"}}, "layout.pageSize"),
        ({"layout": {"marginTop": 81}}, "layout.marginTop"),
        ({"typography": {"textAlign": "right"}}, "typography.textAlign"),
        ({"theme": {"link": "red; } body { display:none"}}, "theme.link"),
        ({"document": {"lang": "italiano!"}}, "document.lang"),
        ({"layout": {"watermark": {"opacity": 2}}}, "layout.watermark.opacity"),
        ({"headerFooter": {"headerFontSize": 3}}, "headerFooter.headerFontSize"),
        ({"pdf": {"engine": "latex"}}, "pdf.engine"),
    ],
)
def test_invalid_settings(override, match):
    with pytest.raises(SettingsError, match=match):
        validate_settings(override)


def test_unknown_settings_keys_are_ignored_but_known_defaults_survive():
    settings = validate_settings({"unknown": {"foo": "bar"}, "typography": {"unknownOption": True}})
    assert "unknown" in settings  # deep merge keeps the provided key
    assert settings["typography"]["bodySize"] == DEFAULT_SETTINGS["typography"]["bodySize"]


def test_filename_sanitisation_blocks_traversal():
    assert sanitize_filename("../../etc/passwd") == "etc-passwd.pdf"
    assert sanitize_filename('report: "finale"?.pdf') == "report finale.pdf"
    assert sanitize_filename("   ") == "documento.pdf"
    assert sanitize_filename("relazione", extension=".md") == "relazione.md"
    assert sanitize_filename("batch1.md") == "batch1.pdf"
    assert sanitize_filename("appunti.markdown") == "appunti.pdf"


def test_filename_in_settings_is_sanitised():
    settings = validate_settings({"document": {"filename": "../fuori/pericolo.pdf"}})
    assert settings["document"]["filename"] == "fuori-pericolo"


def test_missing_nested_settings_are_filled_from_defaults():
    settings = validate_settings({"layout": {"cover": {"enabled": True}}})
    assert settings["layout"]["cover"]["title"] == ""
    assert settings["layout"]["watermark"]["text"] == DEFAULT_SETTINGS["layout"]["watermark"]["text"]
    assert settings["theme"]["name"] == "light"
