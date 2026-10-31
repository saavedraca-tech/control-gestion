"use client";
import { fmtValor, type Estrella, type Semaforo } from "@/lib/api";

export const claseSem = (s: Semaforo) => (s === "sin meta" ? "sinmeta" : s);
const TEXTO: Record<Semaforo, string> = { verde: "En meta", amarillo: "Atención", rojo: "Fuera de meta", gris: "Sin dato", "sin meta": "Sin meta" };

export function TarjetaKpi({ e }: { e: Estrella }) {
  return (
    <div className={`kpi ${claseSem(e.semaforo)}`}>
      <div className="nombre">★ {e.nombre}</div>
      <div className="valor num">{fmtValor(e.valor, e.unidad)}</div>
      <div style={{ fontSize: 12, marginTop: 2 }}><span className={`punto ${claseSem(e.semaforo)}`} />{TEXTO[e.semaforo]}</div>
    </div>
  );
}

export function Puntos({ estrellas }: { estrellas: Estrella[] }) {
  return (
    <span aria-label="Semáforo de los KPIs principales">
      {estrellas.map((e) => <span key={e.nombre} title={`${e.nombre}: ${fmtValor(e.valor, e.unidad)}`} className={`punto ${claseSem(e.semaforo)}`} />)}
    </span>
  );
}

export function MensajeError({ e }: { e: unknown }) {
  return <div className="aviso rojo" role="alert">{e instanceof Error ? e.message : "Ocurrió un error."}</div>;
}
