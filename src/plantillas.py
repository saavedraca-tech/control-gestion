"""Plantillas por rubro (plantillas_rubro/*.yaml) con herencia: cada una hereda de generico.yaml."""
from __future__ import annotations

import copy
from pathlib import Path

from .util import ErrorUsuario, leer_yaml


def disponibles(base: Path) -> list[str]:
    return sorted(p.stem for p in (base / "plantillas_rubro").glob("*.yaml"))


def _fusionar_lista(padre: list, hijo: list, clave: str) -> list:
    out = [copy.deepcopy(x) for x in padre]
    idx = {x.get(clave): i for i, x in enumerate(out)}
    for x in hijo:
        if x.get(clave) in idx:
            out[idx[x[clave]]].update(copy.deepcopy(x))
        else:
            out.append(copy.deepcopy(x))
    return out


def cargar(base: Path, rubro: str) -> dict:
    ruta = base / "plantillas_rubro" / f"{rubro}.yaml"
    if not ruta.exists():
        raise ErrorUsuario(f"No existe la plantilla '{rubro}'. Opciones: {', '.join(disponibles(base))}.")
    hijo = leer_yaml(ruta)
    padre_id = hijo.get("hereda")
    if not padre_id:
        return hijo
    padre = cargar(base, padre_id)
    out = {**copy.deepcopy(padre), **{k: v for k, v in hijo.items() if k not in
                                       ("rubros", "kpis", "reglas_tipicas", "patrones_revisar", "parte_operativo")}}
    out["rubros"] = _fusionar_lista(padre.get("rubros", []), hijo.get("rubros", []), "nombre")
    kpis = _fusionar_lista(padre.get("kpis", []), hijo.get("kpis", []), "id")
    # Primero los ★ (como mucho 8: los del rubro tienen prioridad), después el resto.
    ids_hijo = {k["id"] for k in hijo.get("kpis", [])}
    estrellas = sorted([k for k in kpis if k.get("estrella")], key=lambda k: k["id"] not in ids_hijo)
    for k in estrellas[8:]:
        k["estrella"] = False
    out["kpis"] = [k for k in kpis if k.get("estrella")] + [k for k in kpis if not k.get("estrella")]
    out["reglas_tipicas"] = copy.deepcopy(hijo.get("reglas_tipicas", [])) + copy.deepcopy(padre.get("reglas_tipicas", []))
    out["patrones_revisar"] = list(dict.fromkeys(padre.get("patrones_revisar", []) + hijo.get("patrones_revisar", [])))
    cols = dict((padre.get("parte_operativo") or {}).get("columnas") or {})
    cols.update((hijo.get("parte_operativo") or {}).get("columnas") or {})
    out["parte_operativo"] = {"columnas": cols}
    out["rubro_id"] = rubro
    return out
