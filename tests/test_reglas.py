"""Clasificador, semáforo y metas."""
from types import SimpleNamespace

from src.clasificador import clasificar_proveedor
from src.motor_kpis import meta_del_mes, semaforo


def cliente(reglas, patrones=()):
    rubros = {"rubro_revisar": "A REVISAR", "reglas": reglas, "patrones_revisar": list(patrones),
              "rubros": [{"nombre": "Energía"}, {"nombre": "Combustible"}, {"nombre": "A REVISAR"}]}
    return SimpleNamespace(rubros=rubros, rubro_revisar="A REVISAR")


def test_gana_la_primera_regla():
    c = cliente([{"contiene": "ESTACION", "rubro": "Combustible"}, {"contiene": "ELECTRICIDAD", "rubro": "Energía"}])
    assert clasificar_proveedor(c, "", "ESTACION DE ELECTRICIDAD SA")[0] == "Combustible"


def test_regla_por_cuit_y_texto_sin_acentos_ni_espacios_dobles():
    c = cliente([{"cuit": "30-69027958-0", "rubro": "Combustible"}, {"contiene": "S D P", "rubro": "Energía"}])
    assert clasificar_proveedor(c, "30690279580", "Cualquiera")[0] == "Combustible"
    assert clasificar_proveedor(c, "1", "S D P  S A")[0] == "Energía"


def test_patron_sospechoso_y_sin_regla():
    c = cliente([{"contiene": "ELECTRICIDAD", "rubro": "Energía"}], ["SALUD", "HOGAR"])
    assert clasificar_proveedor(c, "", "Unión Mendoza Salud") == ("A REVISAR", "patrón sospechoso 'SALUD'")
    assert clasificar_proveedor(c, "", "PROVEEDOR NUEVO SRL") == ("A REVISAR", "sin regla")


def test_semaforo():
    assert semaforo(0.38, (None, 0.40), 0.05)[0] == "verde"
    assert semaforo(0.44, (None, 0.40), 0.05)[0] == "amarillo"
    assert semaforo(0.46, (None, 0.40), 0.05)[0] == "rojo"
    assert semaforo(None, (None, 0.40), 0.05)[0] == "gris"
    assert semaforo(3, (2, 4), 1)[0] == "verde"
    assert semaforo(1.2, (2, 4), 1)[0] == "amarillo"
    assert semaforo(5, None, 1)[0] == "sin meta"


def test_meta_por_temporada_y_meses():
    c = SimpleNamespace(temporada=lambda m: "alta" if int(m[5:]) in (11, 12, 1, 2, 3) else "baja")
    k = {"meta": {"alta": [2, 4], "baja": [None, 2]}}
    assert meta_del_mes(k, c, "2026-12") == (2.0, 4.0)
    assert meta_del_mes(k, c, "2026-06") == (None, 2.0)
    k2 = {"meta": 3000000, "direccion": "≥", "solo_meses": [5, 6, 7, 8]}
    assert meta_del_mes(k2, c, "2026-06") == (3000000.0, None)
    assert meta_del_mes(k2, c, "2026-09") is None
