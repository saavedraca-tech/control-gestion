"""Extracción de texto de PDF: pdfplumber y, si falla, pdftotext (poppler)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..util import ErrorUsuario


def texto_pdf(ruta: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(ruta) as pdf:
            texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
        if texto.strip():
            return texto
    except Exception:
        pass
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", str(ruta), "-"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    raise ErrorUsuario(f"No pude leer el texto de {ruta.name}. Si es un PDF escaneado (imagen), "
                       "descargalo de nuevo desde la web de ARCA o del banco.")
