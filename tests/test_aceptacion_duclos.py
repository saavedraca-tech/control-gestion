"""Tests de aceptación con los archivos reales de Duclos (ene–oct 2026). Tolerancia: ±$1 por redondeo."""
import pytest

ENE_SEP = [f"2026-{m:02d}" for m in range(1, 10)]


def suma(serie, meses):
    return float(serie.reindex(meses).sum())


def test_ventas_netas_ene_sep(duclos):
    s = duclos["ctx"].serie
    assert suma(s["ventas_fact"], ENE_SEP) == pytest.approx(36_947_564, abs=1)
    assert s.at["2026-01", "ventas_fact"] == pytest.approx(9_453_470, abs=1)
    assert s.at["2026-07", "ventas_fact"] == pytest.approx(1_944_217, abs=1)


def test_energia_por_fecha_de_factura(duclos):
    s = duclos["ctx"].serie
    energia = suma(s["factura:Energía"], ENE_SEP)
    assert energia == pytest.approx(21_305_634, abs=1)
    assert round(energia / suma(s["ventas_fact"], ENE_SEP), 2) == 0.58


def test_energia_devengada_es_mes_anterior(duclos):
    """La factura de cada mes se imputa al mes anterior: septiembre = factura de octubre."""
    s = duclos["ctx"].serie
    assert s.at["2026-09", "costo:Energía"] == pytest.approx(s.at["2026-10", "factura:Energía"], abs=0.01)
    assert s.at["2026-01", "costo:Energía"] == pytest.approx(s.at["2026-02", "factura:Energía"], abs=0.01)


def test_combustible_y_logistica(duclos):
    s = duclos["ctx"].serie
    assert suma(s["factura:Combustible y logística"], ENE_SEP) == pytest.approx(7_553_748, abs=1)


def test_costo_laboral_f931(duclos):
    s = duclos["ctx"].serie
    assert suma(s["lab_931"], ENE_SEP) == pytest.approx(7_804_959, abs=1)
    assert (s["empleados_931"].reindex(ENE_SEP) == 1).all()


def test_clientes_distintos_y_recurrentes(duclos):
    em = duclos["ctx"].emitidos
    em = em[(em["mes"] >= "2026-01") & (em["mes"] <= "2026-10") & (em["doc"].fillna("") != "")]
    assert em["doc"].nunique() == 596
    assert (em.groupby("doc")["mes"].nunique() >= 3).sum() == 135


def test_octubre_estima_energia_y_f931(duclos):
    """En octubre falta la factura de luz de noviembre y el F.931: se estiman y se avisa."""
    ctx = duclos["ctx"]
    conceptos = {(e["mes"], e["concepto"]) for e in ctx.estimados}
    assert ("2026-10", "Energía") in conceptos
    assert ("2026-10", "Costo laboral F.931") in conceptos
    assert ctx.serie.at["2026-10", "costo:Energía"] == pytest.approx(ctx.serie.at["2026-09", "costo:Energía"])
