/**
 * IMP_Listo web: revisión de los movimientos importados antes de volcarlos a Tesorería.
 * - Marcas: ⚠ Sin regla · ⚠ Posible duplicado · ℹ Sin comprobante · ⚠ Sospechosa (posible gasto personal)
 * - Asignar rubro en la fila (y opcionalmente crear la regla para el cliente)
 * - Aprobar / descartar por fila o en bloque; "Aprobar y volcar" envía las aprobadas a T_Tesoreria.
 * Stack: React 18 + TypeScript + TanStack Query. Sin librería de tabla para que el ejemplo sea autocontenido.
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

type Marca = "sin_regla" | "posible_duplicado" | "sin_comprobante" | "sospechosa";
type Decision = "pendiente" | "aprobar" | "descartar";

export interface FilaStaging {
  id: number;
  nro_fila: number;
  datos: { fecha: string; descripcion: string; contraparte?: string; importe: number; saldo?: number | null };
  rubro_propuesto: string | null;
  tipo_movimiento: string | null;
  marcas: Marca[];
  decision: Decision;
}

interface Props {
  archivoId: string;
  clienteId: string;
  rubros: string[];
  api?: Api;
}

export interface Api {
  filas(archivoId: string): Promise<FilaStaging[]>;
  actualizar(filaId: number, cambios: Partial<Pick<FilaStaging, "rubro_propuesto" | "decision">>): Promise<void>;
  crearRegla(clienteId: string, filaId: number, rubro: string): Promise<{ aplicadaA: number }>;
  volcar(archivoId: string): Promise<{ insertadas: number; omitidas: number }>;
}

const ETIQUETA: Record<Marca, { texto: string; clase: string }> = {
  sin_regla: { texto: "⚠ Sin regla", clase: "bg-amber-100 text-amber-900" },
  posible_duplicado: { texto: "⚠ Posible duplicado", clase: "bg-red-100 text-red-900" },
  sin_comprobante: { texto: "ℹ Sin comprobante", clase: "bg-sky-100 text-sky-900" },
  sospechosa: { texto: "⚠ Posible gasto personal", clase: "bg-rose-100 text-rose-900" },
};

const pesos = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 2 });
const fechaAR = (iso: string) => iso.split("-").reverse().join("/");

const apiPorDefecto: Api = {
  filas: (id) => fetch(`/api/archivos/${id}/staging`).then((r) => r.json()),
  actualizar: (filaId, cambios) =>
    fetch(`/api/staging/${filaId}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cambios) }).then(() => undefined),
  crearRegla: (clienteId, filaId, rubro) =>
    fetch(`/api/clientes/${clienteId}/reglas/desde-fila`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ filaId, rubro }) }).then((r) => r.json()),
  volcar: (id) => fetch(`/api/archivos/${id}/aprobar`, { method: "POST" }).then((r) => r.json()),
};

type Filtro = "todas" | "alertas" | Marca;

export default function ConciliacionImpListo({ archivoId, clienteId, rubros, api = apiPorDefecto }: Props) {
  const qc = useQueryClient();
  const clave = ["staging", archivoId];
  const { data: filas = [], isLoading, error } = useQuery({ queryKey: clave, queryFn: () => api.filas(archivoId) });
  const [filtro, setFiltro] = useState<Filtro>("alertas");
  const [crearRegla, setCrearRegla] = useState<Record<number, boolean>>({});
  const [aviso, setAviso] = useState<string | null>(null);

  const refrescar = () => qc.invalidateQueries({ queryKey: clave });

  const actualizar = useMutation({
    mutationFn: ({ id, cambios }: { id: number; cambios: Partial<FilaStaging> }) => api.actualizar(id, cambios),
    // Actualización optimista: la grilla responde al instante y se revierte si falla.
    onMutate: async ({ id, cambios }) => {
      await qc.cancelQueries({ queryKey: clave });
      const previo = qc.getQueryData<FilaStaging[]>(clave);
      qc.setQueryData<FilaStaging[]>(clave, (fs = []) => fs.map((f) => (f.id === id ? { ...f, ...cambios } : f)));
      return { previo };
    },
    onError: (_e, _v, ctx) => ctx?.previo && qc.setQueryData(clave, ctx.previo),
    onSettled: refrescar,
  });

  const regla = useMutation({
    mutationFn: ({ filaId, rubro }: { filaId: number; rubro: string }) => api.crearRegla(clienteId, filaId, rubro),
    onSuccess: (r) => { setAviso(`Regla creada: se aplicó a ${r.aplicadaA} movimiento(s) más.`); refrescar(); },
  });

  const volcar = useMutation({
    mutationFn: () => api.volcar(archivoId),
    onSuccess: (r) => { setAviso(`Se volcaron ${r.insertadas} movimientos a Tesorería (${r.omitidas} omitidos).`); refrescar(); },
  });

  const resumen = useMemo(() => {
    const cuenta = (m: Marca) => filas.filter((f) => f.marcas.includes(m)).length;
    return {
      total: filas.length,
      alertas: filas.filter((f) => f.marcas.length > 0).length,
      sin_regla: cuenta("sin_regla"), posible_duplicado: cuenta("posible_duplicado"),
      sin_comprobante: cuenta("sin_comprobante"), sospechosa: cuenta("sospechosa"),
      aprobables: filas.filter((f) => f.decision !== "descartar" && f.rubro_propuesto).length,
      bloqueantes: filas.filter((f) => f.decision !== "descartar" && !f.rubro_propuesto).length,
    };
  }, [filas]);

  const visibles = filas.filter((f) =>
    filtro === "todas" ? true : filtro === "alertas" ? f.marcas.length > 0 : f.marcas.includes(filtro));

  const asignarRubro = (f: FilaStaging, rubro: string) => {
    actualizar.mutate({ id: f.id, cambios: { rubro_propuesto: rubro, decision: "aprobar" } });
    if (crearRegla[f.id]) regla.mutate({ filaId: f.id, rubro });
  };

  const aprobarSinAlertas = () =>
    filas.filter((f) => f.marcas.length === 0 && f.decision === "pendiente")
      .forEach((f) => actualizar.mutate({ id: f.id, cambios: { decision: "aprobar" } }));

  if (isLoading) return <p className="p-4 text-slate-500">Cargando movimientos…</p>;
  if (error) return <p className="p-4 text-red-700">No se pudieron cargar los movimientos.</p>;

  return (
    <section className="space-y-3 p-4">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="mr-auto text-lg font-semibold text-slate-800">Revisión de importación</h2>
        <button onClick={aprobarSinAlertas} className="rounded border px-3 py-1.5 text-sm">
          Aprobar las {resumen.total - resumen.alertas} sin alertas
        </button>
        <button
          onClick={() => volcar.mutate()}
          disabled={resumen.bloqueantes > 0 || volcar.isPending}
          title={resumen.bloqueantes > 0 ? "Hay movimientos sin rubro: asignalos o descartalos" : ""}
          className="rounded bg-blue-800 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">
          Aprobar y volcar a Tesorería ({resumen.aprobables})
        </button>
      </header>

      {aviso && <div role="status" className="rounded bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{aviso}</div>}

      <nav className="flex flex-wrap gap-1 text-sm" aria-label="Filtros">
        {([["alertas", `Con alerta (${resumen.alertas})`], ["sin_regla", `Sin regla (${resumen.sin_regla})`],
          ["posible_duplicado", `Duplicados (${resumen.posible_duplicado})`],
          ["sin_comprobante", `Sin comprobante (${resumen.sin_comprobante})`],
          ["sospechosa", `Gasto personal (${resumen.sospechosa})`], ["todas", `Todas (${resumen.total})`],
        ] as [Filtro, string][]).map(([k, t]) => (
          <button key={k} onClick={() => setFiltro(k)} aria-pressed={filtro === k}
            className={`rounded-full px-3 py-1 ${filtro === k ? "bg-slate-800 text-white" : "bg-slate-100"}`}>{t}</button>
        ))}
      </nav>

      <div className="overflow-x-auto rounded border">
        <table className="w-full text-sm">
          <thead className="bg-slate-700 text-left text-white">
            <tr>
              <th className="px-2 py-2">Fecha</th><th className="px-2">Descripción</th>
              <th className="px-2 text-right">Importe</th><th className="px-2">Alertas</th>
              <th className="px-2">Rubro</th><th className="px-2">Crear regla</th><th className="px-2">Decisión</th>
            </tr>
          </thead>
          <tbody>
            {visibles.map((f) => (
              <tr key={f.id} className={`border-t ${f.decision === "descartar" ? "opacity-50" : ""}`}>
                <td className="whitespace-nowrap px-2 py-1.5">{fechaAR(f.datos.fecha)}</td>
                <td className="px-2">
                  <div>{f.datos.descripcion}</div>
                  {f.datos.contraparte && <div className="text-xs text-slate-500">{f.datos.contraparte}</div>}
                </td>
                <td className={`whitespace-nowrap px-2 text-right tabular-nums ${f.datos.importe < 0 ? "text-red-700" : ""}`}>
                  {pesos.format(f.datos.importe)}
                </td>
                <td className="px-2">
                  <div className="flex flex-wrap gap-1">
                    {f.marcas.map((m) => (
                      <span key={m} className={`rounded px-1.5 py-0.5 text-xs ${ETIQUETA[m].clase}`}>{ETIQUETA[m].texto}</span>
                    ))}
                  </div>
                </td>
                <td className="px-2">
                  <select aria-label="Rubro" value={f.rubro_propuesto ?? ""}
                    onChange={(e) => asignarRubro(f, e.target.value)}
                    className={`w-48 rounded border px-1 py-0.5 ${!f.rubro_propuesto ? "border-amber-500" : ""}`}>
                    <option value="" disabled>Elegir rubro…</option>
                    {rubros.map((r) => <option key={r}>{r}</option>)}
                  </select>
                </td>
                <td className="px-2 text-center">
                  {f.marcas.includes("sin_regla") && (
                    <input type="checkbox" aria-label="Crear regla con este texto"
                      checked={!!crearRegla[f.id]}
                      onChange={(e) => setCrearRegla({ ...crearRegla, [f.id]: e.target.checked })} />
                  )}
                </td>
                <td className="px-2">
                  <select aria-label="Decisión" value={f.decision}
                    onChange={(e) => actualizar.mutate({ id: f.id, cambios: { decision: e.target.value as Decision } })}
                    className="rounded border px-1 py-0.5">
                    <option value="pendiente">Pendiente</option>
                    <option value="aprobar">Aprobar</option>
                    <option value="descartar">Descartar</option>
                  </select>
                </td>
              </tr>
            ))}
            {visibles.length === 0 && (
              <tr><td colSpan={7} className="px-2 py-6 text-center text-slate-500">No hay movimientos en este filtro.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
