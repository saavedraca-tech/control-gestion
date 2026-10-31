"""Alta de un cliente nuevo a partir de la plantilla de su rubro, con preguntas guiadas.

Uso:
    python nuevo_cliente.py --nombre "Café Hefesto" --rubro gastronomia
    python nuevo_cliente.py --nombre "Café Hefesto" --rubro gastronomia --cuit 30-12345678-9 --si
      (--si: no pregunta nada y usa los valores de la plantilla)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
for _flujo in (sys.stdout, sys.stderr):  # consolas viejas de Windows: no cortar por un símbolo
    try:
        _flujo.reconfigure(errors="replace")
    except AttributeError:
        pass
sys.path.insert(0, str(BASE))

from src import plantillas  # noqa: E402
from src.util import ErrorUsuario, escribir_yaml, slug, solo_digitos  # noqa: E402


def cuit_valido(cuit: str) -> bool:
    d = solo_digitos(cuit)
    if len(d) != 11:
        return False
    pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
    s = sum(int(a) * b for a, b in zip(d[:10], pesos))
    v = 11 - s % 11
    v = 0 if v == 11 else (9 if v == 10 else v)
    return v == int(d[10])


def formatear_cuit(cuit: str) -> str:
    d = solo_digitos(cuit)
    return f"{d[:2]}-{d[2:10]}-{d[10:]}"


class Preguntas:
    def __init__(self, interactivo: bool, entrada=input):
        self.interactivo = interactivo
        self.entrada = entrada

    def texto(self, pregunta: str, defecto: str = "") -> str:
        if not self.interactivo:
            return defecto
        r = self.entrada(f"{pregunta}" + (f" [{defecto}]" if defecto else "") + ": ").strip()
        return r or defecto

    def entero(self, pregunta: str, defecto: int) -> int:
        while True:
            r = self.texto(pregunta, str(defecto))
            if r.isdigit():
                return int(r)
            print("  Escribí un número (por ejemplo 2).")

    def lista_meses(self, pregunta: str, defecto: list) -> list:
        while True:
            r = self.texto(pregunta, ",".join(str(m) for m in defecto))
            if not r.strip():
                return []
            try:
                meses = [int(x) for x in r.replace(" ", "").split(",") if x]
                if all(1 <= m <= 12 for m in meses):
                    return meses
            except ValueError:
                pass
            print("  Escribí los números de mes separados por coma, por ejemplo: 11,12,1,2,3")

    def porcentaje(self, pregunta: str, defecto: float) -> float:
        while True:
            r = self.texto(pregunta, f"{defecto * 100:g}".replace(".", ","))
            try:
                return float(r.replace("%", "").replace(",", ".")) / 100
            except ValueError:
                print("  Escribí el porcentaje, por ejemplo 3,5")


ENCABEZADOS = {
    "empresa.yaml": "Datos de la empresa. Editable: cambiá los valores después de los dos puntos.",
    "rubros.yaml": ("Reglas proveedor -> rubro de gasto. Se busca el texto dentro del nombre del proveedor (sin\n"
                    "importar mayúsculas ni acentos) o el CUIT exacto. Si coincide con dos reglas, gana la PRIMERA.\n"
                    "Lo que no tiene regla o coincide con patrones_revisar va a 'A REVISAR' y sale en Alertas.\n"
                    "Rubros: tipo variable/fijo · devengamiento mes_factura o mes_anterior · operativo: false ·\n"
                    "personal: true (facturas de personal no registrado)."),
    "kpis.yaml": ("KPIs activos. estrella: tarjeta grande (máx. 8) · meta / direccion (≥ o ≤) / tolerancia en la unidad\n"
                  "del KPI (0.05 = 5 puntos %) · meta: [min, max] rango · meta: {alta: ..., baja: ...} por temporada ·\n"
                  "solo_meses: [5, 6] · activo: false para apagarlo. Fórmulas en src/biblioteca_kpis.py.\n"
                  "parte_operativo.columnas: rol del sistema -> nombre de la columna en el CSV del parte diario."),
    "impuestos.yaml": ("Ingresos Brutos. criterio: pendiente (muestra rango mín–máx y alerta), tipo_comprobante,\n"
                       "lista_cuit o porcentaje."),
    "personal.yaml": ("Nómina. registrado: true (en el F.931) o false. Pagos a no registrados: cada mes en\n"
                      "entrada/AAAA-MM/pagos_personal.csv (persona;monto)."),
}


def armar_config(p: dict, rubro: str, nombre: str, razon: str, cuit: str, actividad: str = "",
                 jurisdiccion: str = "Mendoza", unidad: str | None = None, plural: str | None = None,
                 temporada_alta: list | None = None, socios: list | None = None, n_registrados: int = 0,
                 no_registrados: list | None = None, alicuotas: dict | None = None) -> dict:
    """Arma los 5 archivos de configuración (como dicts) a partir de una plantilla de rubro ya cargada.
    Lo usan este comando y la versión web."""
    u = p.get("unidad_sugerida") or {}
    unidad = unidad or u.get("nombre", "unidad")
    plural = plural or (u.get("plural") if unidad == u.get("nombre") else unidad + "s")
    alta, juris, n_reg = temporada_alta or [], jurisdiccion, n_registrados
    socios, nombres_noreg = socios or [], no_registrados or []
    actividad = actividad or p.get("descripcion", "")
    acts = [dict(a) for a in (p.get("iibb") or {}).get("actividades") or []]
    for a in acts:
        if alicuotas and a["nombre"] in alicuotas:
            a["alicuota"] = float(alicuotas[a["nombre"]])
    empresa = {
        "razon_social": razon, "nombre_corto": slug(nombre).replace("_", " ").title().replace(" ", ""),
        "cuit": formatear_cuit(cuit), "rubro": rubro, "actividad": actividad, "jurisdiccion": juris,
        "activo": True, "unidad_fisica": {"nombre": unidad, "plural": plural}, "temporada_alta": alta,
        "rubro_principal": p.get("rubro_principal"), "socios": socios or ["Socio 1 (completar)"],
        "estimar_faltantes": True, "caja": p.get("caja"), "banco": p.get("banco"),
        "alta": date.today().strftime("%d/%m/%Y"),
    }
    rubros = {"rubro_revisar": p.get("rubro_revisar", "A REVISAR"), "rubros": p.get("rubros", []),
              "reglas": p.get("reglas_tipicas", []), "patrones_revisar": p.get("patrones_revisar", []),
              "movimientos_bancarios": p.get("movimientos_bancarios", [])}
    kpis = {"kpis": p.get("kpis", []), "parte_operativo": p.get("parte_operativo", {"columnas": {}}),
            "clientes": p.get("clientes", {"dias_perdido": 60})}
    iibb = dict(p.get("iibb") or {})
    iibb["actividades"] = acts
    iibb["jurisdiccion"] = juris
    impuestos = {"iibb": iibb}
    personas = [{"nombre": f"Empleado registrado {i + 1}", "registrado": True} for i in range(n_reg)]
    personas += [{"nombre": n, "registrado": False, "alias": [], "sueldo_bruto_regularizacion": None}
                 for n in nombres_noreg]
    personal = {"personas": personas,
                "regularizacion": {"sueldo_bruto_por_defecto": "ultimo_f931", "incluir_sac": True}}

    return {"empresa": empresa, "rubros": rubros, "kpis": kpis, "impuestos": impuestos, "personal": personal}


def crear(base: Path, nombre: str, rubro: str, preg: Preguntas, cuit: str | None = None,
          forzar: bool = False) -> Path:
    p = plantillas.cargar(base, rubro)
    cid = slug(nombre)
    carpeta = base / "clientes" / cid
    if carpeta.exists() and not forzar:
        raise ErrorUsuario(f"Ya existe la carpeta clientes/{cid}. Elegí otro nombre o borrala primero.")

    print(f"\nAlta de cliente: {nombre} · plantilla {p.get('nombre', rubro)}")
    print("Apretá Enter para aceptar el valor entre corchetes.\n")
    razon = preg.texto("Razón social", nombre)
    while True:
        cuit = cuit or preg.texto("CUIT (con o sin guiones)", "")
        if cuit_valido(cuit):
            break
        print("  El CUIT no es válido (revisá los 11 dígitos).")
        if not preg.interactivo:
            raise ErrorUsuario("Falta un CUIT válido: usá --cuit 30-12345678-9.")
        cuit = None
    actividad = preg.texto("Actividad (en pocas palabras)", p.get("descripcion", ""))
    juris = preg.texto("Jurisdicción de IIBB", "Mendoza")
    u = p.get("unidad_sugerida") or {}
    unidad = preg.texto("¿Qué unidad física vende? (kg, litro, cubierto, hora...)", u.get("nombre", "unidad"))
    plural = preg.texto("Plural de la unidad", u.get("plural") if unidad == u.get("nombre") else unidad + "s")
    alta = preg.lista_meses("Meses de temporada alta (números separados por coma; vacío = sin temporada)",
                            p.get("temporada_alta_sugerida") or [])
    socios = [s.strip() for s in preg.texto("Socios (separados por coma)", "").split(",") if s.strip()]
    n_reg = preg.entero("¿Cuántas personas están registradas (en el F.931)?", 0)
    n_noreg = preg.entero("¿Cuántas personas trabajan SIN registrar?", 0)
    nombres_noreg = []
    for i in range(n_noreg):
        nombres_noreg.append(preg.texto(f"  Nombre de la persona no registrada {i + 1}", f"No registrado {i + 1}"))
    acts = (p.get("iibb") or {}).get("actividades") or []
    for a in acts:
        a["alicuota"] = preg.porcentaje(f"Alícuota de IIBB para '{a['nombre']}' (%)", float(a["alicuota"]))

    configs = armar_config(p, rubro, nombre, razon=razon, cuit=cuit, actividad=actividad, jurisdiccion=juris,
                           unidad=unidad, plural=plural, temporada_alta=alta, socios=socios, n_registrados=n_reg,
                           no_registrados=nombres_noreg, alicuotas={a["nombre"]: a["alicuota"] for a in acts})

    cfg = carpeta / "config"
    for clave, datos in configs.items():
        escribir_yaml(cfg / f"{clave}.yaml", datos, ENCABEZADOS[f"{clave}.yaml"])
    hoy = date.today().strftime("%Y-%m")
    for d in ["datos", "salida", f"entrada/{hoy}"]:
        (carpeta / d).mkdir(parents=True, exist_ok=True)
    (carpeta / "entrada" / "LEEME.txt").write_text(
        "Cada mes crear una carpeta AAAA-MM (por ejemplo 2026-11) y dejar ahí:\n"
        "  - CSV de comprobantes EMITIDOS y RECIBIDOS de ARCA (Mis Comprobantes > Exportar CSV)\n"
        "  - PDF del F.931 del mes\n"
        "  - PDF del extracto bancario (opcional)\n"
        "  - parte_diario.csv, saldos.csv, pagos_personal.csv, ventas_sin_comprobante.csv (opcionales)\n"
        "Después correr:  python cierre.py --cliente " + cid + " --mes AAAA-MM\n", encoding="utf-8")
    from src.config import cargar_cliente
    cargar_cliente(base, cid)  # valida que lo generado sea correcto
    print(f"\n✔ Cliente creado en {carpeta}")
    print(f"  Revisá las reglas de proveedores en {cfg / 'rubros.yaml'} y las metas en {cfg / 'kpis.yaml'}.")
    print(f"  Primer cierre: python cierre.py --cliente {cid} --mes AAAA-MM")
    return carpeta


def main(argv=None, base: Path = BASE, entrada=input) -> int:
    ap = argparse.ArgumentParser(description="Alta de un cliente nuevo.")
    ap.add_argument("--nombre", required=True, help='nombre del cliente, ej.: "Café Hefesto"')
    ap.add_argument("--rubro", required=True,
                    help="plantilla: " + ", ".join(plantillas.disponibles(base)))
    ap.add_argument("--cuit", help="CUIT del cliente")
    ap.add_argument("--si", action="store_true", help="no preguntar: usar los valores de la plantilla")
    ap.add_argument("--forzar", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--base", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    base = Path(a.base) if a.base else base
    try:
        crear(base, a.nombre, a.rubro, Preguntas(not a.si, entrada), a.cuit, a.forzar)
        return 0
    except ErrorUsuario as e:
        print(f"\nERROR: {e}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nAlta cancelada.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
