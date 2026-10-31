"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, fmtMes, fmtValor, type ClienteFila } from "@/lib/api";
import { MensajeError, Puntos } from "./componentes";

export default function Panel() {
  const q = useQuery({ queryKey: ["clientes"], queryFn: () => api<ClienteFila[]>("/api/clientes") });
  const yo = useQuery({ queryKey: ["yo"], queryFn: () => api<{ rol: string }>("/api/yo") });
  const clientes = [...(q.data ?? [])].sort((a, b) =>
    (b.ultimo_resumen?.rojos ?? -1) - (a.ultimo_resumen?.rojos ?? -1) || a.razon_social.localeCompare(b.razon_social));

  return (
    <>
      <div className="fila" style={{ alignItems: "center" }}>
        <div><h1>Clientes</h1><p className="sub">Ordenados por prioridad: más indicadores en rojo primero.</p></div>
        {yo.data?.rol !== "socio_cliente" && <div style={{ flex: "0 0 auto" }}><Link className="boton primario" href="/clientes/nuevo">+ Nuevo cliente</Link></div>}
      </div>
      {q.isLoading && <p className="sub">Cargando…</p>}
      {q.error && <MensajeError e={q.error} />}
      {q.data?.length === 0 && <div className="tarjeta">Todavía no hay clientes. Creá el primero con “Nuevo cliente”.</div>}
      <div className="grilla">
        {clientes.map((c) => {
          const r = c.ultimo_resumen;
          return (
            <Link key={c.id} href={`/clientes/${c.id}`} className="tarjeta" style={{ color: "inherit", textDecoration: "none", opacity: c.activo ? 1 : .6 }}>
              <div style={{ fontWeight: 700 }}>{c.razon_social}</div>
              <div className="sub">{c.rubro} · CUIT {c.cuit} · {c.archivos} archivo(s)</div>
              {c.ultimo_mes ? (
                <div style={{ marginTop: 8 }}>
                  <div className="sub">Último cierre: {fmtMes(c.ultimo_mes)} {c.ultimo_estado !== "listo" && `(${c.ultimo_estado})`}</div>
                  {r && <>
                    <div className="num">Ventas {fmtValor(r.ventas, "pesos")} · Resultado <b className={r.resultado !== null && r.resultado < 0 ? "rojo" : ""} style={{ background: "none" }}>{fmtValor(r.resultado, "pesos")}</b></div>
                    <div style={{ marginTop: 6 }}><Puntos estrellas={r.estrellas} /></div>
                    <div className="sub">{r.rojos} en rojo · {r.alertas_altas} alerta(s) alta(s)</div>
                  </>}
                </div>
              ) : <div className="sub" style={{ marginTop: 8 }}>Sin cierres todavía.</div>}
            </Link>
          );
        })}
      </div>
    </>
  );
}
