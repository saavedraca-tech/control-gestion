"""Cierre mensual de control de gestión.

Uso:
    python cierre.py --cliente <cliente> --mes 2026-11
    python cierre.py --todos --mes 2026-11
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

BASE = Path(__file__).resolve().parent
for _flujo in (sys.stdout, sys.stderr):  # consolas viejas de Windows: no cortar por un símbolo
    try:
        _flujo.reconfigure(errors="replace")
    except AttributeError:
        pass
sys.path.insert(0, str(BASE))

from src import alertas as mod_alertas  # noqa: E402
from src import contexto, historico, motor_kpis  # noqa: E402
from src.config import cargar_cliente, listar_clientes  # noqa: E402
from src.personal import escenario_regularizacion  # noqa: E402
from src.reportes import estudio, excel, powerbi, resumen  # noqa: E402
from src.util import ErrorUsuario, fmt_pesos, fmt_valor, mes_nombre, validar_mes  # noqa: E402


def cerrar_cliente(base: Path, cliente_id: str, mes: str, silencioso: bool = False) -> dict:
    def log(t=""):
        if not silencioso:
            print(t)

    c = cargar_cliente(base, cliente_id)
    log(f"\n=== {c.nombre} · cierre de {mes_nombre(mes)} ===")
    carga = historico.cargar(c)
    log(f"  Archivos leídos: {carga.leidos} nuevos o modificados, {carga.sin_cambios} ya procesados"
        + (f" · con error: {len(carga.errores)}" if carga.errores else ""))
    for e in carga.errores:
        log(f"    ✗ {e['archivo']}: {e['detalle']}")
    if carga.base.empty:
        raise ErrorUsuario(f"No hay datos para {c.nombre}. Dejá los archivos del mes en {c.entrada / mes}.")

    ctx = contexto.construir(c, carga.base, mes)
    if not (ctx.serie.at[mes, "n_facturas"] if "n_facturas" in ctx.serie else 0):
        log(f"  ⚠ No hay comprobantes emitidos de {mes_nombre(mes)}. ¿Falta descargar 'Mis Comprobantes'?")
    kpis = motor_kpis.evaluar(ctx)
    tabla = motor_kpis.tabla_mes(kpis, mes)
    esc = escenario_regularizacion(c, ctx.serie, mes, ctx.personal)
    alertas = mod_alertas.generar(ctx, carga, esc)

    salida = c.salida / mes
    salida.mkdir(parents=True, exist_ok=True)
    corto = c.empresa.get("nombre_corto") or c.id
    ruta_xlsx = salida / f"Tablero_{corto}_{mes}.xlsx"
    excel.generar(ctx, tabla, alertas, esc, ruta_xlsx)
    alertas.assign(monto=alertas["monto"].round(2)).to_csv(
        salida / f"alertas_{mes}.csv", sep=";", decimal=",", index=False, encoding="utf-8-sig")
    datos_res = resumen.armar(ctx, tabla, alertas, esc)
    md = resumen.a_markdown(datos_res)
    (salida / f"Resumen_reunion_{mes}.md").write_text(md, encoding="utf-8")
    resumen.a_pdf(md, salida / f"Resumen_reunion_{mes}.pdf")
    powerbi.exportar_cliente(ctx, kpis)

    log(f"  Ventas: {fmt_pesos(ctx.v('ventas_tot'))} · Resultado operativo: {fmt_pesos(ctx.v('resultado'))}")
    for r in tabla[tabla["estrella"]].itertuples():
        marca = {"verde": "🟢", "amarillo": "🟡", "rojo": "🔴", "gris": "⚪"}.get(r.semaforo, "▫️")
        log(f"    {marca} {r.nombre}: {fmt_valor(r.valor, r.unidad)}")
    altas = int((alertas["gravedad"] == "Alta").sum())
    log(f"  Alertas: {altas} alta(s), {int((alertas['gravedad'] == 'Media').sum())} media(s)")
    log(f"  Archivos generados en {salida}")

    return {"id": c.id, "nombre": c.nombre, "rubro": c.empresa.get("rubro", ""), "ctx": ctx, "kpis": kpis,
            "carga": carga,
            "tabla": tabla, "alertas": alertas, "salida": salida, "excel": ruta_xlsx,
            "rojos": int((tabla["semaforo"] == "rojo").sum()),
            "amarillos": int((tabla["semaforo"] == "amarillo").sum()),
            "sin_dato": int((tabla["semaforo"] == "gris").sum()), "alertas_altas": altas,
            "estrellas": tabla[tabla["estrella"]][["nombre", "valor", "unidad", "semaforo"]].to_dict("records")}


def main(argv=None, base: Path = BASE) -> int:
    ap = argparse.ArgumentParser(description="Cierre mensual de control de gestión (ARFinance).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--cliente", help="carpeta del cliente dentro de clientes/ (nombre de la carpeta)")
    g.add_argument("--todos", action="store_true", help="procesa todos los clientes activos")
    ap.add_argument("--mes", required=True, help="mes a cerrar, formato AAAA-MM (ej.: 2026-11)")
    ap.add_argument("--base", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    base = Path(a.base) if a.base else base
    try:
        mes = validar_mes(a.mes)
        if a.cliente:
            cerrar_cliente(base, a.cliente, mes)
        else:
            resultados = []
            for cid in listar_clientes(base):
                try:
                    c = cargar_cliente(base, cid)
                    if not c.activo:
                        print(f"\n(—) {c.nombre}: inactivo, se saltea.")
                        continue
                    resultados.append(cerrar_cliente(base, cid, mes))
                except ErrorUsuario as e:
                    print(f"\n✗ {cid}: {e}")
                    resultados.append({"id": cid, "nombre": cid, "error": str(e)})
                except Exception as e:  # un cliente con problemas no frena a los demás
                    traceback.print_exc()
                    resultados.append({"id": cid, "nombre": cid, "error": f"{type(e).__name__}: {e}"})
            ruta = estudio.generar(base, mes, resultados)
            print(f"\nResumen del estudio: {ruta}")
        destino = powerbi.consolidar_estudio(base)
        print(f"Exportación Power BI del estudio: {destino}")
        return 0
    except ErrorUsuario as e:
        print(f"\nERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
