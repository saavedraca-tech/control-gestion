"""Carga y valida la configuración de un cliente (clientes/<cliente>/config/*.yaml)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import ErrorUsuario, leer_yaml, solo_digitos

ARCHIVOS = ["empresa.yaml", "rubros.yaml", "kpis.yaml", "impuestos.yaml", "personal.yaml"]


@dataclass
class Cliente:
    id: str
    carpeta: Path
    empresa: dict
    rubros: dict
    kpis: dict
    impuestos: dict
    personal: dict
    avisos: list = field(default_factory=list)

    # --- atajos
    @property
    def nombre(self) -> str:
        return self.empresa.get("razon_social", self.id)

    @property
    def cuit(self) -> str:
        return solo_digitos(self.empresa.get("cuit", ""))

    @property
    def unidad(self) -> str:
        return (self.empresa.get("unidad_fisica") or {}).get("nombre", "unidad")

    @property
    def unidad_plural(self) -> str:
        u = self.empresa.get("unidad_fisica") or {}
        return u.get("plural") or (self.unidad + "s")

    @property
    def activo(self) -> bool:
        return bool(self.empresa.get("activo", True))

    def temporada(self, mes: str) -> str:
        alta = self.empresa.get("temporada_alta") or []
        return "alta" if int(mes[5:7]) in alta else "baja"

    @property
    def entrada(self) -> Path:
        return self.carpeta / "entrada"

    @property
    def datos(self) -> Path:
        return self.carpeta / "datos"

    @property
    def salida(self) -> Path:
        return self.carpeta / "salida"

    def rubro(self, nombre: str) -> dict:
        for r in self.rubros.get("rubros", []):
            if r["nombre"] == nombre:
                return r
        return {}

    @property
    def rubro_revisar(self) -> str:
        return self.rubros.get("rubro_revisar", "A REVISAR")


def cargar_cliente(base: Path, cliente_id: str) -> Cliente:
    carpeta = base / "clientes" / cliente_id
    if not carpeta.is_dir():
        existentes = listar_clientes(base)
        raise ErrorUsuario(f"No existe el cliente '{cliente_id}'. Clientes cargados: "
                           f"{', '.join(existentes) or 'ninguno'}. "
                           "Para dar uno de alta usá: python nuevo_cliente.py --nombre \"...\" --rubro ...")
    cfg = {}
    for a in ARCHIVOS:
        cfg[a.split(".")[0]] = leer_yaml(carpeta / "config" / a)
    c = Cliente(id=cliente_id, carpeta=carpeta, **cfg)
    validar(c)
    return c


def listar_clientes(base: Path) -> list[str]:
    d = base / "clientes"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if (p / "config" / "empresa.yaml").exists())


def validar(c: Cliente) -> None:
    errores = []
    if len(c.cuit) != 11:
        errores.append("empresa.yaml: el CUIT tiene que tener 11 dígitos.")
    nombres = [r.get("nombre") for r in c.rubros.get("rubros", [])]
    if c.rubro_revisar not in nombres:
        errores.append(f"rubros.yaml: falta el rubro '{c.rubro_revisar}' en la lista de rubros.")
    for i, regla in enumerate(c.rubros.get("reglas", []) + c.rubros.get("movimientos_bancarios", []), 1):
        if regla.get("rubro") not in nombres:
            errores.append(f"rubros.yaml: la regla {i} ({regla.get('contiene') or regla.get('cuit')}) "
                           f"apunta al rubro '{regla.get('rubro')}', que no está en la lista de rubros.")
        if not (regla.get("contiene") or regla.get("cuit")):
            errores.append(f"rubros.yaml: la regla {i} no tiene 'contiene' ni 'cuit'.")
    for r in c.rubros.get("rubros", []):
        if r.get("devengamiento", "mes_factura") not in ("mes_factura", "mes_anterior"):
            errores.append(f"rubros.yaml: el rubro '{r['nombre']}' tiene devengamiento "
                           f"'{r.get('devengamiento')}'. Usá mes_factura o mes_anterior.")
    from .biblioteca_kpis import BIBLIOTECA
    for k in c.kpis.get("kpis", []):
        base_id = k.get("base", k.get("id"))
        if base_id not in BIBLIOTECA:
            errores.append(f"kpis.yaml: el KPI '{k.get('id')}' usa la fórmula '{base_id}', que no existe "
                           f"en la biblioteca. Opciones: {', '.join(sorted(BIBLIOTECA))}.")
        if k.get("direccion") not in (None, "≥", "≤", ">=", "<="):
            errores.append(f"kpis.yaml: el KPI '{k.get('id')}' tiene dirección '{k.get('direccion')}'. Usá ≥ o ≤.")
    crit = (c.impuestos.get("iibb") or {}).get("criterio", "pendiente")
    if crit not in ("pendiente", "tipo_comprobante", "lista_cuit", "porcentaje"):
        errores.append(f"impuestos.yaml: criterio '{crit}' no válido. Usá pendiente, tipo_comprobante, "
                       "lista_cuit o porcentaje.")
    if errores:
        raise ErrorUsuario("Hay problemas en la configuración de " + c.id + ":\n  - " + "\n  - ".join(errores))
