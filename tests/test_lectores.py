"""Lectores sobre los archivos reales de Duclos y casos especiales."""
from pathlib import Path

import pytest

from src.historico import cargar
from src.lectores import arca, bancos, f931
from src.util import ErrorUsuario

CUIT = "30717547353"


def _uno(base, patron):
    return next((base / "clientes" / "duclos" / "entrada").glob(patron))


def test_emitidos_columnas_y_signo(base_duclos):
    e = arca.leer(_uno(base_duclos, "*/*emitidos*.csv"), CUIT)
    assert len(e) == 1719
    assert set(e["tipo_cbte"].unique()) == {1, 3, 6}
    assert (e.loc[e["tipo_cbte"] == 3, "signo"] == -1).all()
    assert e["fuente"].iloc[0] == "emitidos"


def test_recibidos_factura_c_neto_igual_total(base_duclos):
    r = arca.leer(_uno(base_duclos, "*/*recibidos*.csv"), CUIT)
    c = r[r["letra"] == "C"]
    assert len(c) == 9
    assert (c["neto"] - c["total"]).abs().max() < 0.01
    # Tiques: lo que no está en neto + IVA queda como "no discriminado"
    assert r["no_discriminado"].sum() == pytest.approx(1_583_009.83, abs=0.01)


def test_archivo_de_otro_cuit(base_duclos, tmp_path):
    origen = _uno(base_duclos, "*/*emitidos*.csv")
    otro = tmp_path / origen.name.replace(CUIT, "30999999993")
    otro.write_bytes(origen.read_bytes())
    with pytest.raises(ErrorUsuario, match="otro CUIT"):
        arca.leer(otro, CUIT)


def test_f931_septiembre(base_duclos):
    d = f931.leer(_uno(base_duclos, "2026-09/*931*.pdf"), CUIT).set_index("concepto")["valor"]
    assert d["empleados"] == 1
    assert d["rem1"] == pytest.approx(655036.01)
    assert d["c351"] == pytest.approx(122304.52)
    assert d["c352"] == pytest.approx(38694.11)
    assert d["c312"] == pytest.approx(65539.00)
    assert d["c028"] == pytest.approx(424.62)
    assert d["costo_laboral"] == pytest.approx(881998.26)


@pytest.mark.parametrize("mes", ["2026-01", "2026-06", "2026-07", "2026-08"])
def test_extracto_cierra_con_saldos(base_duclos, mes):
    df, info = bancos.leer(_uno(base_duclos, f"{mes}/Extracto*.pdf"), CUIT)
    movs = df[df["concepto"] != "SALDO_FINAL"]
    assert info["correcciones"] == 0
    assert movs["valor"].sum() == pytest.approx(info["saldo_final"] - info["saldo_inicial"], abs=0.01)


def test_extracto_saldo_deudor_con_signo_al_final(base_duclos):
    df, info = bancos.leer(_uno(base_duclos, "2026-07/Extracto*.pdf"), CUIT)
    assert df["saldo"].min() < 0           # "39.107,35-" se lee como negativo
    assert info["saldo_final"] == pytest.approx(44311.90)
    assert (df["concepto"] == "SUSCRIPCION FIMA").any()   # el código de origen no se come palabras


def test_reprocesar_no_duplica(base_duclos):
    """Volver a leer los mismos archivos (p. ej. porque se los copió de nuevo) no duplica nada."""
    import os
    from src.config import cargar_cliente
    c = cargar_cliente(base_duclos, "duclos")
    n1 = len(cargar(c).base)
    for f in (base_duclos / "clientes" / "duclos" / "entrada").glob("*/*.csv"):
        os.utime(f)  # cambia la fecha de modificación: obliga a releer
    r = cargar(c)
    assert r.leidos >= 2
    assert len(r.base) == n1
    assert not r.base["clave"].duplicated().any()
