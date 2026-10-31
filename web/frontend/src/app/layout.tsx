import "./globals.css";
import type { Metadata, Viewport } from "next";
import Proveedores from "./proveedores";

export const metadata: Metadata = { title: "Control de gestión", description: "Tableros mensuales de clientes PyME" };
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-AR">
      <body><Proveedores>{children}</Proveedores></body>
    </html>
  );
}
