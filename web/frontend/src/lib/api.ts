import { createClient, type Session } from "@supabase/supabase-js";

export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL ?? "http://localhost:54321",
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "anon",
);

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Semaforo = "verde" | "amarillo" | "rojo" | "gris" | "sin meta";
export interface Estrella { nombre: string; valor: number | null; unidad: string; semaforo: Semaforo }
export interface Alerta { gravedad: "Alta" | "Media" | "Info"; tipo: string; mes: string; detalle: string;
  monto: number | null; que_hacer: string }
export interface Resumen {
  ventas: number | null; resultado: number | null; caja: number | null; rojos: number; amarillos: number;
  sin_dato: number; alertas_altas: number; alertas_medias: number; mes_incompleto: boolean;
  estimados: string[]; estrellas: Estrella[]; alertas: Alerta[];
}
export interface ClienteFila {
  id: string; slug: string; razon_social: string; cuit: string; rubro: string; activo: boolean;
  ultimo_mes: string | null; ultimo_estado: string | null; ultimo_resumen: Resumen | null; archivos: number;
}
export interface Archivo { id: string; mes: string; nombre: string; tamano_bytes: number; tipo_detectado: string | null;
  estado: "pendiente" | "procesado" | "con_error" | "ignorado"; detalle: string | null; subido_en: string }
export interface Cierre { id: string; mes: string; estado: "en_cola" | "procesando" | "listo" | "error";
  resumen: Resumen | null; error: string | null; creado_en: string; terminado_en: string | null }
export interface Plantilla { id: string; nombre: string; descripcion: string; unidad: string;
  actividades_iibb: { nombre: string; alicuota: number }[] }

export class ErrorApi extends Error { constructor(public status: number, msg: string) { super(msg); } }

async function token(): Promise<string | null> {
  const { data } = await supabase.auth.getSession();
  return (data.session as Session | null)?.access_token ?? null;
}

export async function api<T>(ruta: string, init: RequestInit = {}): Promise<T> {
  const t = await token();
  const r = await fetch(`${API}${ruta}`, {
    ...init,
    headers: { ...(init.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      ...(t ? { Authorization: `Bearer ${t}` } : {}), ...(init.headers ?? {}) },
  });
  if (!r.ok) {
    let msg = `Error ${r.status}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg: string }) => d.msg).join(". ") : msg;
    } catch { /* respuesta sin JSON */ }
    throw new ErrorApi(r.status, msg);
  }
  return r.json() as Promise<T>;
}

export async function descargar(cierreId: string, tipo: "excel" | "pdf" | "md" | "alertas") {
  const t = await token();
  const r = await fetch(`${API}/api/cierres/${cierreId}/descargas/${tipo}`, { headers: t ? { Authorization: `Bearer ${t}` } : {} });
  if (!r.ok) throw new ErrorApi(r.status, "No se pudo descargar");
  const nombre = /filename="(.+)"/.exec(r.headers.get("Content-Disposition") ?? "")?.[1] ?? `${tipo}`;
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: nombre });
  a.click();
  URL.revokeObjectURL(url);
}

// Formato argentino
const pesos = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });
const num = (d: number) => new Intl.NumberFormat("es-AR", { maximumFractionDigits: d, minimumFractionDigits: d });
export function fmtValor(v: number | null | undefined, unidad: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "sin dato";
  switch (unidad) {
    case "pesos": return pesos.format(v);
    case "pct": return `${num(1).format(v * 100)} %`;
    case "dias": return `${num(1).format(v)} días`;
    case "horas": return `${num(1).format(v)} h`;
    case "decimal": return num(2).format(v);
    default: return num(0).format(v);
  }
}
export const fmtMes = (m: string) => {
  const [a, n] = m.split("-");
  return `${["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"][Number(n) - 1]}-${a.slice(2)}`;
};
export const fmtFecha = (iso: string) => new Date(iso).toLocaleString("es-AR", { dateStyle: "short", timeStyle: "short" });
export const mesAnterior = () => {
  const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
