import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from motor import REGLAS_GLOBALES, num_ar, procesar_archivo, regla_desde_correccion  # noqa: E402

CSV_DH = """BANCO X - Movimientos de cuenta
Cuenta 123
FECHA;CONCEPTO;DEBITO;CREDITO;SALDO
01/07/2026;IMP. DEB. LEY 25413 GRAL.;558,00;;41.915,35
02/07/2026;TRANSFERENCIA DE TERCEROS JUAN;;12.600,00;54.515,35
02/07/2026;TRANSFERENCIA DE TERCEROS JUAN;;12.600,00;67.115,35
03/07/2026;PAGO PROVEEDOR XYZ;30.000,00;;37.115,35
""".encode()


def test_num_ar():
    assert num_ar("1.234,56") == 1234.56
    assert num_ar("23.357,35-") == -23357.35
    assert num_ar("(100,00)") == -100.0
    assert num_ar("-1234.5") == -1234.5


def test_debe_haber_reglas_y_duplicados():
    r = procesar_archivo(CSV_DH, "mov.csv", "cta1", REGLAS_GLOBALES, set())
    assert r.perfil == "banco_debe_haber"
    f = r.filas
    assert [x["datos"]["importe"] for x in f] == [-558.0, 12600.0, 12600.0, -30000.0]
    assert f[0]["rubro_propuesto"] == "Impuestos y tasas"
    assert "sin_regla" in f[3]["marcas"]
    assert f[1]["huella"] != f[2]["huella"]          # dos transferencias iguales el mismo día no se pisan
    r2 = procesar_archivo(CSV_DH, "mov.csv", "cta1", REGLAS_GLOBALES, {x["huella"] for x in f})
    assert all("posible_duplicado" in x["marcas"] for x in r2.filas)   # recarga del mismo extracto
    assert r2.estado == "duplicado"


def test_regla_desde_correccion():
    rg = regla_desde_correccion("cli1", "PAGO PROVEEDOR XYZ 00012345 15/07", "Mantenimiento")
    assert rg.patron == "PAGO PROVEEDOR XYZ"
    assert rg.coincide({"descripcion": "PAGO PROVEEDOR XYZ 99999", "importe": -1})
