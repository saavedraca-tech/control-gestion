-- Esquema PostgreSQL (Supabase) · Plataforma de control de gestión PyME
-- Tres capas: ORIGEN (archivos y filas crudas) -> NORMALIZACIÓN (tablas T_*) -> TABLEROS (vistas/materializadas).
-- Multicliente: toda tabla de negocio lleva estudio_id + cliente_id y se protege con Row Level Security.

create extension if not exists pgcrypto;

-- ============================================================ organización y seguridad
create table estudios (
  id uuid primary key default gen_random_uuid(),
  nombre text not null,
  creado_en timestamptz not null default now()
);

create table usuarios (
  id uuid primary key,                       -- = auth.users.id de Supabase
  estudio_id uuid not null references estudios(id),
  nombre text not null,
  rol text not null check (rol in ('admin','consultor','socio_cliente','lectura'))
);

create table clientes (
  id uuid primary key default gen_random_uuid(),
  estudio_id uuid not null references estudios(id),
  slug text not null,                        -- 'duclos'
  razon_social text not null,
  cuit char(11) not null,
  rubro text not null,                       -- fabrica | comercio | servicios | gastronomia | generico
  jurisdiccion text,
  unidad_fisica text, unidad_plural text,
  temporada_alta smallint[] default '{}',
  activo boolean not null default true,
  config jsonb not null default '{}'::jsonb, -- equivalente a empresa.yaml (caja, banco, estimaciones)
  unique (estudio_id, cuit), unique (estudio_id, slug)
);

-- Acceso de usuarios-socios a sus propios clientes (los consultores ven todo el estudio)
create table usuarios_clientes (
  usuario_id uuid references usuarios(id) on delete cascade,
  cliente_id uuid references clientes(id) on delete cascade,
  primary key (usuario_id, cliente_id)
);

create table unidades_negocio (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  nombre text not null,                      -- 'Mayorista', 'Minorista', 'Servicios'
  unique (cliente_id, nombre)
);

create table cuentas (                       -- bancos, billeteras, procesadores, tarjetas, brokers, cajas
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  tipo text not null check (tipo in ('banco','billetera','procesador','tarjeta','broker','caja','inversion')),
  entidad text not null,                     -- 'Galicia', 'Mercado Pago', 'Payway', 'IOL'
  numero text, moneda char(3) not null default 'ARS',
  es_disponibilidad boolean not null default true,   -- FIMA/FCI = false (inversión, no caja)
  perfil_id uuid,                            -- perfil de importación por defecto
  unique (cliente_id, entidad, numero)
);

-- ============================================================ configuración (maestros)
create table rubros (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  nombre text not null,
  linea_pyl text not null check (linea_pyl in
    ('ventas','cmv','costo_directo','estructura','suministros','personal','impuestos','financieros',
     'amortizaciones','no_operativo','a_revisar','movimiento_interno')),
  tipo text not null default 'fijo' check (tipo in ('fijo','variable')),
  devengamiento text not null default 'mes_factura' check (devengamiento in ('mes_factura','mes_anterior')),
  unique (cliente_id, nombre)
);

create table perfiles_importacion (          -- M_Perfiles
  id uuid primary key default gen_random_uuid(),
  estudio_id uuid references estudios(id),   -- null = perfil global del sistema
  codigo text not null unique,               -- 'galicia_pdf', 'mp_csv', 'payway_xlsx', 'generico_signo'
  nombre text not null,
  formato text not null check (formato in ('csv','xlsx','pdf')),
  firma_deteccion jsonb not null,            -- {"encabezados":[...]} o {"texto_contiene":[...]}
  mapeo jsonb not null,                      -- columnas -> campos normalizados, modo de importe, fechas, decimales
  version int not null default 1
);

create table reglas_clasificacion (          -- M_Reglas
  id uuid primary key default gen_random_uuid(),
  estudio_id uuid references estudios(id),   -- null = regla global (200+ reglas argentinas)
  cliente_id uuid references clientes(id),   -- null = aplica a todos los clientes del estudio
  prioridad int not null,                    -- menor = se evalúa antes; gana la primera
  ambito text not null check (ambito in ('tesoreria','compras','ventas')),
  campo text not null default 'texto' check (campo in ('texto','cuit','contraparte')),
  operador text not null default 'contiene' check (operador in ('contiene','igual','regex','empieza')),
  patron text not null,
  signo text check (signo in ('ingreso','egreso')),  -- opcional: sólo débitos / sólo créditos
  rubro_nombre text not null,                -- se resuelve contra rubros del cliente
  tipo_movimiento text,                      -- 'impuesto_cheque','sircreb','vep','f931','transferencia_interna'...
  es_sospechosa boolean not null default false,       -- patrón de gasto personal -> A REVISAR
  activa boolean not null default true,
  creada_por uuid references usuarios(id), creada_en timestamptz default now()
);
create index on reglas_clasificacion (coalesce(cliente_id, '00000000-0000-0000-0000-000000000000'), ambito, prioridad);

create table supuestos_macro (               -- T_Supuestos (global por estudio)
  estudio_id uuid not null references estudios(id),
  mes date not null,                         -- primer día del mes
  ipc numeric(14,6), ipim numeric(14,6),
  tc_oficial numeric(14,4), tc_mep numeric(14,4), tc_ccl numeric(14,4),
  primary key (estudio_id, mes)
);

-- ============================================================ CAPA 1: ORIGEN
create table archivos (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  nombre_original text not null,
  storage_path text not null,                -- bucket privado de Supabase Storage
  sha256 char(64) not null,
  tamano_bytes bigint not null,
  periodo date,                              -- mes al que corresponde (si se detecta)
  perfil_id uuid references perfiles_importacion(id),
  estado text not null default 'pendiente' check (estado in
    ('pendiente','procesando','para_revisar','aprobado','con_alerta','duplicado','error','descartado')),
  detalle_estado text,
  subido_por uuid references usuarios(id), subido_en timestamptz not null default now(),
  unique (cliente_id, sha256)                -- el mismo archivo no se procesa dos veces
);

create table filas_staging (                 -- IMP_Listo: lo que el usuario revisa antes de aprobar
  id bigserial primary key,
  archivo_id uuid not null references archivos(id) on delete cascade,
  cliente_id uuid not null references clientes(id) on delete cascade,
  destino text not null check (destino in ('tesoreria','ventas','compras','personal','mermas')),
  nro_fila int not null,
  datos jsonb not null,                      -- campos normalizados propuestos
  huella char(64) not null,                  -- hash de fecha+importe+cuenta+texto normalizado
  regla_id uuid references reglas_clasificacion(id),
  rubro_propuesto text,
  marcas text[] not null default '{}',       -- {'sin_regla','posible_duplicado','sin_comprobante','sospechosa'}
  duplicado_de bigint,                       -- id en T_* si ya existe
  decision text not null default 'pendiente' check (decision in ('pendiente','aprobar','descartar')),
  editado_por uuid references usuarios(id)
);
create index on filas_staging (archivo_id, decision);

-- ============================================================ CAPA 2: NORMALIZACIÓN
-- Campos de moneda comunes: importe (moneda original), moneda, importe_ars (nominal),
-- y columnas calculadas en vista: ars_constante (AxI) y usd_mep / usd_oficial.

create table t_tesoreria (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  cuenta_id uuid not null references cuentas(id),
  fecha date not null,
  descripcion text not null, contraparte text, contraparte_cuit char(11),
  importe numeric(18,2) not null,            -- con signo: + ingreso / - egreso
  moneda char(3) not null default 'ARS', importe_ars numeric(18,2) not null,
  bruto numeric(18,2), comision numeric(18,2), impuestos numeric(18,2),   -- billeteras / procesadores
  saldo numeric(18,2),
  rubro_id uuid references rubros(id), tipo_movimiento text,
  comprobante_id bigint,                     -- vínculo a t_compras/t_ventas (conciliación)
  unidad_negocio_id uuid references unidades_negocio(id),
  huella char(64) not null,
  archivo_id uuid references archivos(id), fila_staging_id bigint,
  unique (cliente_id, huella)
);
create index on t_tesoreria (cliente_id, fecha);

create table t_ventas (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  fecha date not null, tipo_cbte smallint, letra char(1), punto_venta int, numero bigint,
  receptor_cuit varchar(11), receptor_nombre text,
  neto numeric(18,2) not null, iva numeric(18,2) not null default 0, otros_trib numeric(18,2) default 0,
  total numeric(18,2) not null, signo smallint not null default 1,
  moneda char(3) default 'ARS', tipo_cambio numeric(14,4) default 1,
  unidad_negocio_id uuid references unidades_negocio(id), canal text,
  sin_comprobante boolean not null default false,
  archivo_id uuid references archivos(id),
  unique (cliente_id, tipo_cbte, punto_venta, numero, receptor_cuit)
);

create table t_compras (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  fecha date not null, tipo_cbte smallint, letra char(1), punto_venta int, numero bigint,
  emisor_cuit varchar(11), emisor_nombre text,
  neto numeric(18,2) not null, iva numeric(18,2) default 0, otros_trib numeric(18,2) default 0,
  no_discriminado numeric(18,2) default 0, total numeric(18,2) not null, signo smallint not null default 1,
  rubro_id uuid references rubros(id), regla_id uuid references reglas_clasificacion(id),
  mes_imputado date not null,                -- devengamiento (p. ej. energía a mes vencido)
  archivo_id uuid references archivos(id),
  unique (cliente_id, tipo_cbte, punto_venta, numero, emisor_cuit)
);

create table legajos (                       -- matriz de personal
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  nombre text not null, cuil char(11), cct text, categoria text,
  registrado boolean not null default true,
  fecha_ingreso date, fecha_egreso date, unidad_negocio_id uuid references unidades_negocio(id)
);

create table t_personal (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  periodo date not null,
  legajo_id uuid references legajos(id),     -- null = total del F.931
  origen text not null check (origen in ('f931','recibo','pago_no_registrado','factura_personal')),
  basico numeric(18,2), adicionales numeric(18,2), rem1 numeric(18,2),
  c351 numeric(18,2), c352 numeric(18,2), c312 numeric(18,2), c028 numeric(18,2),
  c301 numeric(18,2), c302 numeric(18,2), sac_provision numeric(18,2),
  costo_total numeric(18,2) not null, empleados int,
  archivo_id uuid references archivos(id),
  unique (cliente_id, periodo, origen, legajo_id)
);

create table t_mermas (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  fecha date not null, unidad_negocio_id uuid references unidades_negocio(id), turno text,
  causa text not null, producto text, cantidad numeric(14,3) not null, unidad text,
  costo_unitario numeric(18,4), valor numeric(18,2) generated always as (cantidad * coalesce(costo_unitario,0)) stored
);

create table t_operativo_diario (            -- parte diario (unidades, stock, medidor, paradas)
  cliente_id uuid not null references clientes(id) on delete cascade,
  fecha date not null, variable text not null, valor numeric(18,4) not null,
  primary key (cliente_id, fecha, variable)
);

create table t_presupuesto (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  version text not null,                     -- 'base_historica','ajuste_volumen','objetivo','oficial'
  mes date not null, rubro_id uuid references rubros(id), unidad_negocio_id uuid references unidades_negocio(id),
  importe_ars numeric(18,2), importe_usd numeric(18,2), nota text,
  unique (cliente_id, version, mes, rubro_id, unidad_negocio_id)
);

create table t_balance (                     -- saldos de cierre mensuales para NOF / ratios / Dupont
  cliente_id uuid not null references clientes(id) on delete cascade,
  mes date not null, concepto text not null check (concepto in
    ('existencias','realizable','disponible','activo_corriente','activo_no_corriente','proveedores',
     'deuda_cp','deuda_lp','patrimonio_neto','amortizaciones_mes')),
  importe numeric(18,2) not null,
  primary key (cliente_id, mes, concepto)
);

create table kpi_definiciones (
  id text primary key,                        -- biblioteca común (= src/biblioteca_kpis.py)
  nombre text not null, categoria text not null, unidad text not null, formula text not null
);
create table kpi_cliente (                    -- kpis.yaml del cliente
  cliente_id uuid references clientes(id) on delete cascade, kpi_id text references kpi_definiciones(id),
  alias text, estrella boolean default false, params jsonb default '{}',
  meta jsonb, direccion text, tolerancia numeric, orden int,
  primary key (cliente_id, kpi_id, alias)
);

create table decisiones (
  id bigserial primary key,
  cliente_id uuid not null references clientes(id) on delete cascade,
  fecha date not null, decision text not null, responsable text, vence date,
  estado text not null default 'Pendiente' check (estado in ('Pendiente','En curso','Hecha','Descartada')),
  notas text
);

create table auditoria (
  id bigserial primary key, cliente_id uuid, usuario_id uuid, accion text not null,
  entidad text not null, entidad_id text, antes jsonb, despues jsonb, en timestamptz default now()
);

-- ============================================================ CAPA 3: TABLEROS (vistas)
-- Coeficiente AxI acumulado al cierre: indice_cierre / ipc_del_mes (equivale a =Indice_Cierre/BUSCARX(...)).
create or replace function coef_axi(p_estudio uuid, p_mes date, p_cierre date) returns numeric
language sql stable as $$
  select (select ipc from supuestos_macro where estudio_id = p_estudio and mes = date_trunc('month', p_cierre))
       / nullif((select ipc from supuestos_macro where estudio_id = p_estudio and mes = date_trunc('month', p_mes)), 0)
$$;

create or replace view v_pyl_mensual as
select c.cliente_id, c.mes, r.linea_pyl, r.nombre as rubro, c.unidad_negocio_id, sum(c.importe) as importe_ars
from (
  select cliente_id, date_trunc('month', fecha)::date mes, null::uuid unidad_negocio_id,
         neto * signo as importe, null::uuid rubro_id from t_ventas
  union all
  select cliente_id, mes_imputado, null, -neto * signo, rubro_id from t_compras
  union all
  select cliente_id, periodo, null, -costo_total, null from t_personal
) c left join rubros r on r.id = c.rubro_id
group by 1,2,3,4,5;

-- NOF = Existencias + Realizable + Disponible - Proveedores - Deuda CP
create or replace view v_nof as
select cliente_id, mes,
  coalesce(sum(importe) filter (where concepto in ('existencias','realizable','disponible')),0)
- coalesce(sum(importe) filter (where concepto in ('proveedores','deuda_cp')),0) as nof
from t_balance group by 1,2;

-- ============================================================ Row Level Security (ejemplo)
alter table clientes enable row level security;
create policy clientes_del_estudio on clientes using (
  estudio_id = (select estudio_id from usuarios where id = auth.uid())
  and ((select rol from usuarios where id = auth.uid()) <> 'socio_cliente'
       or id in (select cliente_id from usuarios_clientes where usuario_id = auth.uid()))
);
-- Repetir el mismo patrón (por cliente_id) en archivos, filas_staging, t_*, decisiones.
