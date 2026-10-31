"""Cierre completo: Duclos (archivos reales) y un cliente ficticio de gastronomía (datos sintéticos)."""
import re
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

import cierre
import sintetico
from conftest import RAIZ, copiar_base

HOJAS = ["Tablero", "Resultado mensual", "Gráficos", "Clientes", "Compras", "Personal", "Alertas",
         "Decisiones", "Leyenda"]


def test_cierre_duclos_genera_todo(base_duclos):
    r = cierre.cerrar_cliente(base_duclos, "duclos", "2026-09", silencioso=True)
    sal = r["salida"]
    for f in ["Tablero_Duclos_2026-09.xlsx", "Resumen_reunion_2026-09.md", "Resumen_reunion_2026-09.pdf",
              "alertas_2026-09.csv"]:
        assert (sal / f).exists(), f
    wb = load_workbook(sal / "Tablero_Duclos_2026-09.xlsx")
    for h in HOJAS:
        assert h in wb.sheetnames
    assert sum(r["tabla"]["estrella"]) == 8
    al = pd.read_csv(sal / "alertas_2026-09.csv", sep=";")
    assert "Personal no registrado" in set(al["tipo"])         # alerta permanente
    assert "IIBB sin criterio" in set(al["tipo"])
    assert (al["tipo"] == "Gasto a revisar").any()
    for t in ["hechos_movimientos", "hechos_kpis", "dim_calendario", "dim_contrapartes", "dim_rubros", "dim_kpis",
              "dim_empresa"]:
        assert (base_duclos / "clientes" / "duclos" / "powerbi" / f"{t}.parquet").exists()


def test_resumen_una_pagina(base_duclos):
    from pypdf import PdfReader
    r = cierre.cerrar_cliente(base_duclos, "duclos", "2026-09", silencioso=True)
    assert len(PdfReader(r["salida"] / "Resumen_reunion_2026-09.pdf").pages) == 1
    md = (r["salida"] / "Resumen_reunion_2026-09.md").read_text(encoding="utf-8")
    assert md.count("\n1. ") + md.count("\n2. ") + md.count("\n3. ") <= 3 + 3  # títulos + hasta 3 preguntas
    assert "Para decidir hoy" in md


def test_decisiones_se_conservan(base_duclos):
    r = cierre.cerrar_cliente(base_duclos, "duclos", "2026-09", silencioso=True)
    ruta = r["excel"]
    wb = load_workbook(ruta)
    ws = wb["Decisiones"]
    ws["A6"], ws["B6"], ws["C6"], ws["E6"] = "15/10/2026", "Pedir presupuesto de cámara nueva", "Socio 1", "Pendiente"
    wb.save(ruta)
    r2 = cierre.cerrar_cliente(base_duclos, "duclos", "2026-10", silencioso=True)
    ws2 = load_workbook(r2["excel"])["Decisiones"]
    assert ws2["B6"].value == "Pedir presupuesto de cámara nueva"
    md = (r2["salida"] / "Resumen_reunion_2026-10.md").read_text(encoding="utf-8")
    assert "Pedir presupuesto de cámara nueva" in md


@pytest.fixture(scope="module")
def sint(tmp_path_factory):
    base = copiar_base(tmp_path_factory.mktemp("base_sint"))
    esperado = sintetico.generar(base)
    r = cierre.cerrar_cliente(base, esperado["id"], "2026-03", silencioso=True)
    return base, esperado, r


def test_sintetico_ventas_costos_y_resultado(sint):
    base, e, r = sint
    s = r["ctx"].serie
    for mes, v in e["ventas"].items():
        assert s.at[mes, "ventas_fact"] == pytest.approx(v, abs=0.01), mes
        for rubro, costo in e["costos"][mes].items():
            assert s.at[mes, "costo:" + rubro] == pytest.approx(costo), (mes, rubro)
        assert s.at[mes, "revisar"] == pytest.approx(e["revisar"][mes])
        assert s.at[mes, "lab_931"] == pytest.approx(e["costo_931"])
    mar = "2026-03"
    lab = e["costo_931"] + e["pago_nr"]
    assert s.at[mar, "lab_total"] == pytest.approx(lab)
    iibb = e["ventas"][mar] * e["alicuota"]
    esperado = e["ventas"][mar] - sum(e["costos"][mar].values()) - lab - iibb
    assert s.at[mar, "resultado"] == pytest.approx(esperado, abs=0.01)


def test_sintetico_kpis(sint):
    base, e, r = sint
    t = r["tabla"].set_index("id")
    mar = "2026-03"
    assert t.at["food_cost", "valor"] == pytest.approx(300000 / e["ventas"][mar])
    assert t.at["precio_promedio_unidad", "valor"] == pytest.approx(e["ventas"][mar] / e["unidades"][mar])
    assert t.at["merma_pct", "valor"] == pytest.approx(e["descartadas"][mar] / e["producidas"][mar])
    assert t.at["personal_no_registrado_cant", "valor"] == 1
    assert r["ctx"].serie.at[mar, "caja"] == pytest.approx(e["caja_mar"])           # sin el FCI
    assert r["ctx"].serie.at[mar, "inversiones"] == pytest.approx(e["inversiones_mar"])
    assert t.at["clientes_activos", "valor"] == 3                                    # el anónimo no cuenta


def test_sintetico_sin_rastros_de_duclos(sint):
    base, e, r = sint
    wb = load_workbook(r["excel"])
    texto = " ".join(str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value)
    md = (r["salida"] / "Resumen_reunion_2026-03.md").read_text(encoding="utf-8")
    for prohibido in ["Duclos", "DUCLOS", "bolsa", "EDEMSA", "hielo", "30717547353", "FIMA"]:
        assert prohibido not in texto, prohibido
        assert prohibido not in md, prohibido
    assert "cubierto" in texto.lower()


def test_codigo_sin_datos_de_un_cliente():
    """Nada específico de Duclos en el código: todo tiene que estar en la configuración."""
    prohibidos = re.compile(r"duclos|30-?71754735-?3|edemsa|policuyo|hielo|\bbolsas?\b|rumaos|supercanal|"
                            r"alpes|electricidad", re.I)
    archivos = list((RAIZ / "src").rglob("*.py")) + [RAIZ / "cierre.py", RAIZ / "nuevo_cliente.py"]
    hallados = [(a.name, m.group(0)) for a in archivos for m in prohibidos.finditer(a.read_text(encoding="utf-8"))]
    assert hallados == []


def test_todos_y_resumen_del_estudio(tmp_path):
    hay_duclos = (RAIZ / "clientes" / "duclos" / "entrada").is_dir()   # no está en el repositorio (privacidad)
    base = copiar_base(tmp_path, ["duclos"] if hay_duclos else [])
    sintetico.generar(base)
    assert cierre.main(["--todos", "--mes", "2026-03"], base=base) == 0
    ruta = base / "estudio" / "salida" / "2026-03" / "Resumen_estudio_2026-03.xlsx"
    ws = load_workbook(ruta)["Clientes"]
    esperados = {"Café Prueba Sintética"} | ({"DUCLOS SAS"} if hay_duclos else set())
    nombres = {ws.cell(row=r, column=2).value for r in range(5, 5 + len(esperados))}
    assert nombres == esperados
    pbi = pd.read_parquet(base / "estudio" / "powerbi" / "hechos_kpis.parquet")
    assert set(pbi["cliente_id"]) == {"cafe_prueba_sintetica"} | ({"duclos"} if hay_duclos else set())


def test_nuevo_cliente_interactivo(tmp_path):
    import nuevo_cliente
    base = copiar_base(tmp_path)
    respuestas = iter(["Hefesto SRL", "30-71234567-0", "30712345671", "", "Mendoza", "", "", "", "Ana, Pedro",
                       "2", "1", "Pedro Ayudante", "4"])
    salidas = []
    rc = nuevo_cliente.main(["--nombre", "Café Hefesto", "--rubro", "gastronomia"], base=base,
                            entrada=lambda p: (salidas.append(p), next(respuestas))[1])
    assert rc == 0
    from src.config import cargar_cliente
    c = cargar_cliente(base, "cafe_hefesto")
    assert c.cuit == "30712345671"                      # el primer CUIT era inválido y lo volvió a pedir
    assert c.unidad == "cubierto"
    assert len([p for p in c.personal["personas"] if not p["registrado"]]) == 1
    assert c.impuestos["iibb"]["actividades"][0]["alicuota"] == pytest.approx(0.04)
