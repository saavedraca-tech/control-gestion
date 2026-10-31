"use client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, supabase } from "@/lib/api";

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Barra() {
  const router = useRouter();
  const yo = useQuery({ queryKey: ["yo"], queryFn: () => api<{ email: string; rol: string; estudio: string }>("/api/yo") });
  return (
    <header className="barra">
      <div className="contenedor">
        <Link href="/">Control de gestión</Link>
        <span className="sub ocultar-movil" style={{ color: "#dbe7f3" }}>{yo.data?.estudio}</span>
        <span className="espacio" />
        <span className="ocultar-movil" style={{ fontSize: 13 }}>{yo.data?.email}</span>
        <button onClick={async () => { await supabase.auth.signOut(); qc.clear(); router.replace("/login"); }}>Salir</button>
      </div>
    </header>
  );
}

export default function Proveedores({ children }: { children: React.ReactNode }) {
  const ruta = usePathname();
  const router = useRouter();
  const [listo, setListo] = useState(false);
  const [conSesion, setConSesion] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => { setConSesion(!!data.session); setListo(true); });
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setConSesion(!!s));
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (listo && !conSesion && ruta !== "/login") router.replace("/login");
  }, [listo, conSesion, ruta, router]);

  if (ruta === "/login") return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  if (!listo || !conSesion) return <p className="contenedor sub">Cargando…</p>;
  return (
    <QueryClientProvider client={qc}>
      <Barra />
      <main className="contenedor">{children}</main>
    </QueryClientProvider>
  );
}
