"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { supabase } from "@/lib/api";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [clave, setClave] = useState("");
  const [msg, setMsg] = useState<{ tipo: "rojo" | "verde"; texto: string } | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true); setMsg(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password: clave });
    setEnviando(false);
    if (error) setMsg({ tipo: "rojo", texto: "Email o contraseña incorrectos." });
    else router.replace("/");
  }

  async function enlace() {
    if (!email) { setMsg({ tipo: "rojo", texto: "Escribí tu email primero." }); return; }
    setEnviando(true);
    const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
    setEnviando(false);
    setMsg(error ? { tipo: "rojo", texto: "No se pudo enviar el enlace." }
      : { tipo: "verde", texto: `Te mandamos un enlace a ${email}. Abrilo desde este dispositivo.` });
  }

  return (
    <main className="contenedor" style={{ maxWidth: 420, paddingTop: 60 }}>
      <h1>Control de gestión</h1>
      <p className="sub">Ingresá con el usuario que te dio el estudio.</p>
      <form className="tarjeta" onSubmit={entrar}>
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="clave">Contraseña</label>
        <input id="clave" type="password" autoComplete="current-password" value={clave} onChange={(e) => setClave(e.target.value)} />
        {msg && <div className={`aviso ${msg.tipo}`} role="alert">{msg.texto}</div>}
        <div className="fila" style={{ marginTop: 14 }}>
          <button className="primario" type="submit" disabled={enviando || !clave}>Entrar</button>
          <button type="button" onClick={enlace} disabled={enviando}>Entrar sin contraseña (por email)</button>
        </div>
      </form>
    </main>
  );
}
