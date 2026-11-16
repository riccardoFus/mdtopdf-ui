"""Validation and converter unit tests (errors, files, missing assets)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import SettingsError, validate_settings
from app.converter import convert_document, read_markdown_file, write_markdown_file
from app.markdown_engine import MarkdownError


def test_read_markdown_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="File non trovato"):
        read_markdown_file(tmp_path / "assente.md")


def test_read_markdown_file_rejects_unsupported_extension(tmp_path: Path):
    path = tmp_path / "documento.pdf"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(MarkdownError, match="Estensione non supportata"):
        read_markdown_file(path)


def test_read_markdown_file_handles_bom_and_accents(tmp_path: Path):
    path = tmp_path / "accenti.md"
    path.write_bytes("\ufeff# Perché è così\n\nCittà, più, però.".encode("utf-8"))
    content, resolved = read_markdown_file(path)
    assert "Perché" in content
    assert resolved == path.resolve()


def test_write_and_reopen_markdown(tmp_path: Path):
    target = tmp_path / "nuovo.md"
    written = write_markdown_file(target, "# Ciao\n\nTesto.")
    assert written == target.resolve()
    assert target.read_text(encoding="utf-8").startswith("# Ciao")


def test_write_markdown_missing_directory(tmp_path: Path):
    with pytest.raises(MarkdownError, match="non esiste"):
        write_markdown_file(tmp_path / "manca" / "file.md", "# Ciao")


def test_write_markdown_adds_extension(tmp_path: Path):
    path = write_markdown_file(tmp_path / "senza-estensione", "testo")
    assert path.suffix == ".md"
    assert path.exists()


def test_convert_empty_markdown():
    with pytest.raises(MarkdownError, match="vuoto"):
        convert_document("   \n", validate_settings({}))


def test_convert_invalid_yaml():
    with pytest.raises(MarkdownError, match="YAML frontmatter non valido"):
        convert_document("---\ntitle: [rotto\n---\n# Titolo\n", validate_settings({}))


def test_convert_invalid_settings():
    with pytest.raises(SettingsError, match="bodySize"):
        convert_document("# Titolo\n", {"typography": {"bodySize": 99}})


def test_convert_missing_base_dir(tmp_path: Path):
    with pytest.raises(MarkdownError, match="Cartella di base non valida"):
        convert_document("# Titolo\n", validate_settings({}), base_dir=tmp_path / "non-esiste")


def test_convert_missing_image_is_warning_not_fatal(tmp_path: Path):
    result = convert_document(
        "# Titolo\n\n![Mancante](non-esiste.png)\n",
        validate_settings({}),
        base_dir=tmp_path,
    )
    assert result.page_count >= 1
    assert result.pdf.startswith(b"%PDF")
    assert any("non-esiste.png" in warning["message"] for warning in result.warnings)


def test_convert_accepts_source_path_for_relative_images(tmp_path: Path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "pic.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"/>', encoding="utf-8"
    )
    source = tmp_path / "doc.md"
    source.write_text("# Titolo\n\n![Foto](assets/pic.svg)\n", encoding="utf-8")
    markdown, path = read_markdown_file(source)
    result = convert_document(markdown, validate_settings({}), source_path=path)
    assert not any("Immagine non trovata" in warning["message"] for warning in result.warnings)
    assert result.page_count == 1


def test_convert_frontmatter_title_appears_in_pdf_metadata(tmp_path: Path):
    import io

    from pypdf import PdfReader

    result = convert_document(
        "---\ntitle: Metadato speciale\nauthor: Anna\n---\n# Corpo\n",
        validate_settings({}),
    )
    assert "Metadato speciale" in result.html
    reader = PdfReader(io.BytesIO(result.pdf))
    assert reader.metadata.title == "Metadato speciale"
    assert reader.metadata.author == "Anna"
