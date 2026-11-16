import subprocess
from pathlib import Path
import sys
import tempfile
import os

def md_to_pdf(md_file, pdf_file=None):
    md_path = Path(md_file).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"File non trovato: {md_path}")

    if pdf_file is None:
        pdf_path = md_path.with_suffix(".pdf")
    else:
        pdf_path = Path(pdf_file).resolve()

    # CSS personalizzato per margini ridotti e stile migliorato
    custom_css = """
@page {
    size: A4;
    margin: 1.5cm 1.5cm 2cm 1.5cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-size: 9pt;
        color: #666;
    }
}

body {
    font-family: 'DejaVu Sans', 'Segoe UI', Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.4;
    color: #333;
    margin: 0;
    padding: 0;
}

/* Il titolo del file (metadato) non deve apparire sopra il titolo del documento */
header#title-block-header {
    display: none;
}

h1 {
    font-size: 18pt;
    color: #1a365d;
    border-bottom: 2px solid #2c5282;
    padding-bottom: 0.3em;
    margin-top: 0.5em;
    margin-bottom: 0.8em;
    page-break-after: avoid;
}

h2 {
    font-size: 14pt;
    color: #2c5282;
    border-bottom: 1px solid #4299e1;
    padding-bottom: 0.2em;
    margin-top: 1em;
    margin-bottom: 0.5em;
    page-break-after: avoid;
}

h3 {
    font-size: 12pt;
    color: #2b6cb0;
    margin-top: 0.8em;
    margin-bottom: 0.4em;
    page-break-after: avoid;
}

h4 {
    font-size: 11pt;
    color: #3182ce;
    margin-top: 0.6em;
    margin-bottom: 0.3em;
}

code {
    background-color: #f7fafc;
    border: 1px solid #e2e8f0;
    padding: 0.1em 0.3em;
    border-radius: 3px;
    font-size: 9pt;
    font-family: 'DejaVu Sans Mono', 'Consolas', monospace;
}

pre {
    background-color: #f7fafc;
    border: 1px solid #e2e8f0;
    padding: 0.8em;
    border-radius: 4px;
    overflow-x: visible;
    font-size: 9pt;
    line-height: 1.3;
    /* Manda a capo le righe lunghe invece di tagliarle ai margini */
    white-space: pre-wrap;
    overflow-wrap: break-word;
}

pre code {
    background-color: transparent;
    border: none;
    padding: 0;
}

/* Il template HTML di pandoc impone white-space: pre sul codice:
   forziamo il wrapping anche in armonia con le sue regole. */
pre > code.sourceCode {
    white-space: pre-wrap !important;
    overflow-wrap: break-word;
}

/* Annulla il rientro "appeso" del template pandoc, che spinge le righe
   lunghe oltre il bordo del riquadro. */
pre > code.sourceCode > span {
    display: inline;
    padding-left: 0 !important;
    text-indent: 0 !important;
}

/* Checklist Markdown (- [ ] / - [x] ...).
   I checkbox nativi di WeasyPrint vengono resi male: li sostituiamo
   con un quadratino disegnato in CSS. */
ul.task-list {
    list-style: none;
    padding-left: 0.2em;
}

ul.task-list li {
    list-style: none;
}

ul.task-list li input[type="checkbox"] {
    display: none !important;
}

ul.task-list li label::before {
    content: "";
    display: inline-block;
    width: 0.8em;
    height: 0.8em;
    border: 1.2pt solid #4a5568;
    border-radius: 2px;
    margin-right: 0.45em;
    vertical-align: -0.08em;
}

ul.task-list li label:has(input:checked)::before {
    content: "\2713";
    color: #2c5282;
    font-size: 0.75em;
    font-weight: bold;
    text-align: center;
    line-height: 1.1;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.8em 0;
    font-size: 9pt;
}

th, td {
    border: 1px solid #cbd5e0;
    padding: 0.4em 0.6em;
    text-align: left;
}

th {
    background-color: #edf2f7;
    font-weight: bold;
    color: #2d3748;
}

tr:nth-child(even) {
    background-color: #f7fafc;
}

blockquote {
    border-left: 4px solid #4299e1;
    margin: 0.8em 0;
    padding: 0.5em 1em;
    background-color: #ebf8ff;
    font-style: italic;
}

ul, ol {
    margin: 0.5em 0;
    padding-left: 1.5em;
}

li {
    margin: 0.2em 0;
}

a {
    color: #3182ce;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

img {
    max-width: 100%;
    height: auto;
}

/* Evita interruzioni di pagina inappropriate */
h1, h2, h3, h4, h5, h6 {
    page-break-after: avoid;
}

pre, blockquote {
    page-break-inside: avoid;
}
"""

    # Crea file CSS temporaneo
    with tempfile.NamedTemporaryFile(mode='w', suffix='.css', delete=False) as css_file:
        css_file.write(custom_css)
        css_path = css_file.name

    try:
        cmd = [
            "pandoc",
            # ID di sezione in stile GitHub: mantengono i numeri, così i link
            # interni del tipo #1-modello-di-sicurezza funzionano.
            "--from", "markdown+gfm_auto_identifiers",
            str(md_path),
            "-o", str(pdf_path),
            "--resource-path", str(md_path.parent),
            "--pdf-engine", "weasyprint",
            "--css", css_path,
            "--metadata", f"title={md_path.stem}"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"Warning: {result.stderr}", file=sys.stderr)
        
        return pdf_path
    finally:
        # Rimuovi file CSS temporaneo
        try:
            os.unlink(css_path)
        except:
            pass

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python md_to_pdf.py input.md [output.pdf]")
        sys.exit(1)

    input_md = sys.argv[1]
    output_pdf = sys.argv[2] if len(sys.argv) > 2 else None

    result = md_to_pdf(input_md, output_pdf)
    print(f"Creato: {result}")