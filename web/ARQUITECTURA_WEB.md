# Plataforma web de control de gestión PyME · Arquitectura

Este documento cubre los 5 entregables pedidos. Los archivos que lo acompañan están en esta misma carpeta:

| Entregable | Archivo |
|---|---|
| 1. Arquitectura tecnológica | este documento, §1 |
| 2. Esquema de base de datos | `db/schema.sql` (PostgreSQL / Supabase, con RLS) |
| 3. Flujo de ingesta y reglas | §3 + `backend/ingesta/motor.py` |
| 4a. Parser de extractos / F.931 (Python) | `backend/ingesta/motor.py` (+ `src/lectores/` ya en uso) · tests en `backend/ingesta/test_motor.py` |
| 4b. Vista de conciliación IMP_Listo (React/TS) | `frontend/src/components/ConciliacionImpListo.tsx` (compila con `tsc --strict`) |
| 5. Plan por fases | §5 |

> **Punto de partida:** ya existe un motor en Python **probado con datos reales** de Duclos:
> - lectores de ARCA, F.931 y Galicia;
> - histórico sin duplicados;
> - reglas proveedor → rubro;
> - biblioteca de KPIs con semáforo;
> - Excel, PDF y exportación a Power BI;
> - 31 tests.
>
> La web **no lo reescribe**: lo envuelve. Pasa de "carpetas + YAML + terminal" a "base de datos + navegador".

---

## 1. Arquitectura tecnológica recomendada

```
 Navegador (consultor / socio desde el celular)
        │  HTTPS
 ┌──────▼─────────────────────┐        ┌───────────────────────────────┐
 │ Frontend Next.js (React/TS)│        │ Supabase                       │
 │  - Dashboard multicliente  │◄──────►│  - Auth (usuarios, roles, 2FA) │
 │  - Carga drag & drop       │  JWT   │  - PostgreSQL + RLS por cliente│
 │  - IMP_Listo (conciliación)│        │  - Storage privado (archivos)  │
 │  - Tableros (ECharts)      │        └──────────────▲────────────────┘
 └──────┬─────────────────────┘                       │
        │ REST /api (JWT de Supabase)                 │ SQL
 ┌──────▼──────────────────────────────────────────────┴─┐
 │ Backend Python · FastAPI                               │
 │  - API: clientes, archivos, staging, reglas, KPIs      │
 │  - Motor reutilizado: src/lectores, clasificador,      │
 │    biblioteca_kpis, motor_kpis, reportes (Excel/PDF)   │
 │  - Worker de cola (procesamiento de archivos pesados)  │
 └────────────────────────────────────────────────────────┘
```

| Capa | Elección | Por qué |
|---|---|---|
| Frontend | **Next.js 14 + React 18 + TypeScript**, Tailwind, TanStack Query/Table, **Apache ECharts** | Un solo código para escritorio y celular. ECharts maneja bien series largas, apilados y waterfall (P&L). |
| Backend | **Python 3.12 + FastAPI** | El motor ya está en Python (pandas, pdfplumber, openpyxl, reportlab). Reescribirlo en Node.js significa volver a validar los números de control. |
| Cola | **Dramatiq o RQ + Redis** (o Supabase Edge Function que encola) | Un extracto de 20 páginas tarda unos 5 s y la carga inicial de un año, alrededor de 40 s. No se procesa dentro del request. |
| Base de datos | **PostgreSQL en Supabase** | Relacional (P&L, NOF y presupuesto son joins y agregaciones), RLS por cliente, backups y Auth incluidos. Con `jsonb` se guarda la configuración flexible. |
| Archivos | **Supabase Storage** (bucket privado, URL firmadas) | Los originales quedan guardados para auditar y reprocesar. |
| Parsers | `pdfplumber`, `pypdf`, `pandas`, `openpyxl`, `xlrd` (.xls); **OCR** opcional con `ocrmypdf`/Tesseract solo para PDF escaneados | Los PDF de ARCA y de los bancos son de texto: la OCR solo hace falta como plan B. |
| Hosting | Frontend en **Vercel**, backend y worker en **Render/Railway/Fly.io** (contenedor Docker), Supabase gestionado | Arranque de unos USD 25–45 por mes. Todo se puede mover a un VPS propio después. |
| Observabilidad | Sentry (front y back) y logs estructurados | Saber qué archivo falló y por qué. |

**Seguridad (no negociable: hay sueldos, CUIT y personal no registrado):**
- RLS en todas las tablas con `cliente_id`. El rol `socio_cliente` ve solo sus empresas.
- Doble factor (2FA) para consultores.
- El bucket de archivos es privado.
- Tabla `auditoria` para cambios de reglas y aprobaciones.
- Cifrado en tránsito y en reposo (Supabase).
- Exportación y borrado de los datos de un cliente, para cumplir la Ley 25.326 de datos personales.

---

## 2. Esquema de base de datos

El detalle está en `db/schema.sql`. Mapa de entidades:

```
estudios ─┬─ usuarios ── usuarios_clientes ──┐
          ├─ supuestos_macro (IPC, IPIM, TC)  │
          ├─ perfiles_importacion (M_Perfiles)│
          └─ clientes ◄──────────────────────┘
               ├─ cuentas (banco/billetera/procesador/tarjeta/broker/caja/inversión)
               ├─ unidades_negocio
               ├─ rubros (línea de P&L, fijo/variable, devengamiento)
               ├─ reglas_clasificacion (M_Reglas: global → estudio → cliente, por prioridad)
               │
               ├─ CAPA 1 ORIGEN:     archivos (sha256, estado) ── filas_staging (IMP_Listo: huella, marcas, decisión)
               ├─ CAPA 2 NORMALIZ.:  t_tesoreria · t_ventas · t_compras · t_personal + legajos · t_mermas
               │                     t_operativo_diario · t_presupuesto · t_balance
               └─ CAPA 3 TABLEROS:   v_pyl_mensual · v_nof · kpi_definiciones/kpi_cliente · decisiones
```

Decisiones de diseño:
- **Moneda.** Se guarda `importe` en la moneda original y `importe_ars` nominal. Las versiones **ARS constante (AxI)** y **USD MEP/Oficial** se calculan en vistas a partir de `supuestos_macro`, sin guardarlas. Así un cambio de IPC o de tipo de cambio recalcula todo sin reprocesar. La función `coef_axi()` es la equivalencia exacta de `=Indice_Cierre / BUSCARX(Mes; Supuestos[Mes]; Supuestos[IPC])`.
- **Sin referencias rotas.** Las tablas no tienen "filas" de planilla: los tableros son consultas sobre claves (`cliente_id`, `mes`, `rubro_id`). Las divisiones usan `nullif(x, 0)`, el equivalente de `SIERROR`.
- **Idempotencia.** Hay tres niveles:
  - `archivos.unique(cliente_id, sha256)`: el mismo archivo no entra dos veces;
  - `t_tesoreria.unique(cliente_id, huella)`;
  - `t_ventas` y `t_compras` son únicas por tipo, punto de venta, número y CUIT, igual que en el motor actual.

---

## 3. Flujo de ingesta y algoritmo de reglas

```
Subida ─► 1 Hash ─► 2 Perfil ─► 3 Parseo ─► 4 Normalización ─► 5 Huella ─► 6 Reglas ─► 7 Marcas ─► 8 IMP_Listo ─► 9 Volcado
```

1. **Hash y archivo.** Se calcula el SHA-256 y, si ya existe para el cliente, el archivo queda en estado `duplicado` sin procesarse. Si es nuevo, se guarda en Storage, se crea `archivos(estado='pendiente')` y se encola.
2. **Detección de perfil (M_Perfiles).**
   - **PDF:** se extrae el texto con pdfplumber (pdftotext como respaldo) y se compara contra `firma_deteccion.texto_contiene`. Así se reconocen el F.931, el resumen de Galicia y otros. Si no hay texto, va a OCR.
   - **CSV/XLSX:** se busca la fila de encabezados (los extractos traen títulos arriba) y se elige el perfil con **más encabezados coincidentes**. Si ninguno coincide, el usuario elige el perfil a mano y el sistema le propone guardarlo.
   - **ARCA "Mis Comprobantes":** se reconoce por el encabezado. Se valida que el CUIT del nombre de archivo sea el del cliente.
3. **Parseo según `mapeo.modo_importe`:**
   - `signo`: una columna con + y −;
   - `debe_haber`: débito y crédito en columnas separadas;
   - `dc`: importe más una columna D/C.

   Billeteras y procesadores (Mercado Pago, Ualá, Payway) separan **bruto, comisión e impuestos**. Los números se aceptan como `1.234,56`, `1234.56`, `1.234,56-` (saldo deudor de Galicia) o `(1.234,56)`.
4. **Normalización.**
   - Fecha.
   - Texto en mayúsculas, sin acentos y con espacios simples.
   - Moneda. En ARCA se aplican las mismas reglas que en el motor actual: neto = gravado + no gravado + exento; las notas de crédito restan; en los comprobantes C, neto = total.
5. **Huella (duplicados de movimientos):** `sha256(cuenta | fecha | importe | texto[:60] | ocurrencia)`. La `ocurrencia` numera los movimientos idénticos del mismo día (dos transferencias iguales de $12.600). Así no se confunden entre sí, pero una recarga del mismo extracto sí se detecta.
   Controles adicionales:
   - superposición de período con otro extracto de la misma cuenta;
   - **cadena de saldos:** saldo anterior + importe = saldo. Si no cierra, se marca el error de lectura.
6. **Reglas (M_Reglas):**
   - **Orden:** primero las reglas del cliente, después las del estudio y por último las globales. Dentro de cada nivel se ordenan por `prioridad`. **Gana la primera que coincide.**
   - **Condiciones:** `campo` (texto, CUIT o contraparte), `operador` (contiene, igual, empieza o regex) y, opcionalmente, `signo` (solo ingresos o solo egresos).
   - **Resultado:** cada regla asigna `rubro` y `tipo_movimiento`. Ejemplos de tipos: `impuesto_cheque`, `sircreb`, `vep`, `f931`, `haberes`, `echeq`, `debin`, `inversion`, `deposito_efectivo`.
   - **Reglas sospechosas:** las de gasto personal (SALUD, HOGAR, TURISMO…) tienen `es_sospechosa` y mandan el movimiento a **A REVISAR**.
   - **Movimientos internos:** las transferencias entre cuentas propias y las suscripciones o rescates de FCI quedan como `movimiento_interno`. No son ingreso ni gasto.
7. **Marcas:**
   - `sin_regla`;
   - `posible_duplicado` (la huella ya está en `t_tesoreria`);
   - `sin_comprobante`: egreso sin factura en `t_compras` de ±$1 dentro de ±3 días, si su tipo no es impuesto, comisión ni otro que no lleve factura;
   - `sospechosa`.
8. **IMP_Listo (revisión).**
   - El usuario filtra por alerta, asigna el rubro en la fila y, si tilda **"crear regla"**, el sistema arma una regla del cliente con la parte estable del texto: saca números de operación, CBU y fechas (función `regla_desde_correccion`). Al instante la reaplica a las demás filas pendientes.
   - Las filas sin alertas se aprueban en bloque.
9. **Volcado.**
   - Se hace en una transacción: `insert ... on conflict (cliente_id, huella) do nothing` en `t_tesoreria`.
   - El archivo pasa a `aprobado`.
   - Se recalculan las vistas y KPIs del período afectado (vistas materializadas por cliente y mes, refrescadas por el worker).

---

## 4. Código de muestra

- **`backend/ingesta/motor.py`** incluye:
  - perfiles `mercadopago_csv`, `banco_debe_haber`, `banco_dc`, `generico_signo`, `galicia_pdf` y `f931_pdf`;
  - detección de encabezados;
  - números con formato argentino;
  - huella con ocurrencia;
  - motor de reglas con prioridad y alcance;
  - marcas;
  - creación de reglas a partir de una corrección.

  Para Galicia y F.931 **reutiliza los lectores ya validados** contra los extractos reales de Duclos (`src/lectores/bancos.py` y `f931.py`). Tests: `python -m pytest web/backend/ingesta/test_motor.py` (3 pasan).
- **`frontend/src/components/ConciliacionImpListo.tsx`** incluye:
  - filtros por tipo de alerta y etiquetas ⚠/ℹ;
  - selector de rubro con "crear regla";
  - aprobación por fila y en bloque;
  - actualizaciones optimistas;
  - el botón "Aprobar y volcar", bloqueado mientras haya filas sin rubro;
  - formato `es-AR`.

  Endpoints que consume:

  | Método | Ruta |
  |---|---|
  | `GET` | `/api/archivos/:id/staging` |
  | `PATCH` | `/api/staging/:id` |
  | `POST` | `/api/clientes/:id/reglas/desde-fila` |
  | `POST` | `/api/archivos/:id/aprobar` |

---

## 5. Plan de implementación por fases

| Fase | Duración estimada* | Entrega | Criterio de "listo" |
|---|---|---|---|
| **0. Base** | 1 semana | Repositorio GitHub privado, Docker, CI que corre los 31 tests actuales, proyecto Supabase, `schema.sql` aplicado | CI en verde. Login funcionando. |
| **1. MVP "cierre en la web"** | 3–4 semanas | Alta de cliente (reemplaza `nuevo_cliente.py`); subida drag & drop; procesamiento en cola con el **motor actual**; descarga del Excel, el PDF de la reunión y las alertas; panel multicliente con semáforos ★ | Duclos cerrado desde el navegador con los mismos números de control (ventas $36.947.564, etc.). Los socios ven el PDF desde el celular. |
| **2. Configuración sin YAML** | 2–3 semanas | Pantallas de reglas, rubros, metas, IIBB y personal (los YAML pasan a tablas); importador de los YAML existentes; auditoría de cambios | La contadora reclasifica un proveedor desde la web y el tablero cambia. |
| **3. Tesorería + IMP_Listo** | 3–4 semanas | Perfiles Mercado Pago, Payway/Fiserv, tarjetas y bancos genéricos (signo, D/C, debe/haber); 200+ reglas globales; staging, conciliación y volcado; marca de sin comprobante | 3 extractos reales de distintas entidades importados sin errores; una recarga del mismo extracto da 100 % duplicados. |
| **4. Tableros BI web** | 3–4 semanas | P&L por unidad de negocio; Prime Cost diario/semanal; mermas valorizadas; MAT 12 meses; flujo de caja proyectado a 30/60/90 días; cálculo de NOF, PMM, Dupont, liquidez, ácida, endeudamiento y ROE | Coincide con la planilla modelo para un cliente piloto. Se ve bien en el celular. |
| **5. Presupuesto bimoneda y AxI** | 3 semanas | Supuestos de IPC/IPIM y TC (Oficial, MEP, CCL), con carga mensual o API; etapas del presupuesto (base histórica → volumen → objetivos → oficial); real vs. presupuesto con semáforo y notas | El coeficiente AxI coincide con la fórmula de la planilla. Los desvíos cuadran con el Excel modelo. |
| **6. Producción** | 2 semanas | 2FA, backups probados, Sentry, límites de carga, manual de uso, migración de clientes | Restauración de backup probada. Dos clientes reales trabajando un mes completo. |

\* Para una persona a tiempo completo con experiencia. Con dedicación parcial, multiplicar por 2 o 3.

**Riesgos y cómo se cubren:**
- **El formato de un banco cambia.**
  - Cada perfil está versionado.
  - El control de la cadena de saldos detecta lecturas malas.
  - Un test por perfil usa un extracto real anonimizado.
- **Para Balance, NOF, Dupont y ROE faltan datos.** ARCA y los extractos no traen existencias, deudas ni patrimonio. Hacen falta `t_balance` (carga mensual o balance del estudio). Sin eso esos indicadores muestran "sin dato", igual que hoy.
- **Alcance.** La spec mezcla tres modelos grandes. **Fase 1 aporta valor sola**: el cierre de Duclos en la web. Conviene llegar ahí antes de sumar presupuesto y AxI.
