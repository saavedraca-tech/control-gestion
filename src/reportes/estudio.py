"""Resumen del estudio (cierre --todos): una fila por cliente con sus KPIs ★ y semáforo."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from ..util import fmt_valor, mes_nombre
from .excel import BORDE, C_META, SEM, _encabezado, _fill


def generar(base: Path, mes: str, resultados: list[dict]) -> Path:
    carpeta = base / "estudio" / "salida" / mes
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"Resumen_estudio_{mes}.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws["A1"] = f"Resumen del estudio · {mes_nombre(mes)}"
    ws["A1"].font = Font(bold=True, size=15, color=C_META)
    ws["A2"] = (f"Ordenado por prioridad: más KPIs en rojo y alertas altas primero. Generado el "
                f"{date.today().strftime('%d/%m/%Y')}.")
    ws["A2"].font = Font(italic=True, size=9)
    ws.sheet_view.showGridLines = False
    max_est = max([len(r.get("estrellas", [])) for r in resultados] + [0])
    cab = ["Prioridad", "Cliente", "Rubro", "Estado del cierre", "Rojos", "Amarillos", "Sin dato", "Alertas altas"] + \
          [f"★ {i + 1}" for i in range(max_est)]
    _encabezado(ws, 4, 1, cab)
    orden = sorted(resultados, key=lambda r: (r.get("error") is None, -r.get("rojos", 0), -r.get("alertas_altas", 0)))
    for i, r in enumerate(orden):
        f = 5 + i
        ws.cell(row=f, column=1, value=i + 1)
        nom = ws.cell(row=f, column=2, value=r["nombre"])
        nom.font, nom.alignment = Font(bold=True), Alignment(wrap_text=True, vertical="center")
        ws.cell(row=f, column=3, value=r.get("rubro", ""))
        est = ws.cell(row=f, column=4, value="ERROR: " + r["error"] if r.get("error") else "OK")
        est.alignment = Alignment(wrap_text=True, vertical="top")
        if r.get("error"):
            est.fill, est.font = _fill("FFC7CE"), Font(color="9C0006", bold=True)
        for j, k in enumerate(["rojos", "amarillos", "sin_dato", "alertas_altas"]):
            c = ws.cell(row=f, column=5 + j, value=r.get(k))
            if k in ("rojos", "alertas_altas") and r.get(k):
                c.fill, c.font = _fill("FFC7CE"), Font(bold=True, color="9C0006")
        for j, e in enumerate(r.get("estrellas", [])):
            c = ws.cell(row=f, column=9 + j, value=f"{e['nombre']}\n{fmt_valor(e['valor'], e['unidad'])}")
            bg, fg, _ = SEM.get(e["semaforo"], SEM["gris"])
            c.fill, c.font = _fill(bg), Font(color=fg, bold=True, size=9)
            c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        for j in range(1, len(cab) + 1):
            ws.cell(row=f, column=j).border = BORDE
        ws.row_dimensions[f].height = 42
    anchos = {"A": 9, "B": 38, "C": 13, "D": 22, "E": 8, "F": 10, "G": 9, "H": 10}
    for k, v in anchos.items():
        ws.column_dimensions[k].width = v
    for j in range(max_est):
        ws.column_dimensions[ws.cell(row=4, column=9 + j).column_letter].width = 19
    ws.freeze_panes = "C5"
    ws.page_setup.orientation, ws.page_setup.paperSize = "landscape", ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    wb.save(ruta)
    return ruta
