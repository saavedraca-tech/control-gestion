-- Fase 1 · Cierre mensual en la web.
-- El motor sigue siendo el de Python (src/); la base guarda clientes, su configuración, los archivos
-- subidos y el resultado de cada cierre. Las fases siguientes agregan las tablas T_* de web/db/schema.sql.

create extension if not exists pgcrypto;

create table if not exists estudios (
  id uuid primary key default gen_random_uuid(),
  nombre text not null,
  creado_en timestamptz not null default now()
);

create table if not exists usuarios (
  id uuid primary key,                       -- = auth.users.id
  estudio_id uuid not null references estudios(id),
  email text not null,
  nombre text not null default '',
  rol text not null default 'consultor' check (rol in ('admin','consultor','socio_cliente'))
);

create table if not exists clientes (
  id uuid primary key default gen_random_uuid(),
  estudio_id uuid not null references estudios(id),
  slug text not null,
  razon_social text not null,
  cuit char(11) not null,
  rubro text not null,
  activo boolean not null default true,
  -- Los 5 archivos de configuración del motor (empresa, rubros, kpis, impuestos, personal) como JSON.
  config jsonb not null,
  creado_en timestamptz not null default now(),
  unique (estudio_id, slug),
  unique (estudio_id, cuit)
);

-- Socios de una empresa: ven sólo sus clientes (los consultores ven todos los del estudio).
create table if not exists usuarios_clientes (
  usuario_id uuid references usuarios(id) on delete cascade,
  cliente_id uuid references clientes(id) on delete cascade,
  primary key (usuario_id, cliente_id)
);

create table if not exists archivos (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  mes char(7) not null check (mes ~ '^\d{4}-(0[1-9]|1[0-2])$'),   -- carpeta entrada/AAAA-MM
  nombre text not null,
  storage_path text not null,
  sha256 char(64) not null,
  tamano_bytes bigint not null,
  tipo_detectado text,                       -- emitidos | recibidos | f931 | banco | parte | ... (tras procesar)
  estado text not null default 'pendiente' check (estado in ('pendiente','procesado','con_error','ignorado')),
  detalle text,
  subido_por uuid references usuarios(id),
  subido_en timestamptz not null default now(),
  unique (cliente_id, sha256)
);
create index if not exists archivos_cliente_mes on archivos (cliente_id, mes);

create table if not exists cierres (
  id uuid primary key default gen_random_uuid(),
  cliente_id uuid not null references clientes(id) on delete cascade,
  mes char(7) not null,
  estado text not null default 'en_cola' check (estado in ('en_cola','procesando','listo','error')),
  resumen jsonb,                             -- ventas, resultado, KPIs ★ con semáforo, cantidad de alertas
  salidas jsonb,                             -- {"excel": "path", "pdf": ..., "md": ..., "alertas": ...}
  log text,
  error text,
  pedido_por uuid references usuarios(id),
  creado_en timestamptz not null default now(),
  terminado_en timestamptz
);
create index if not exists cierres_cliente_mes on cierres (cliente_id, mes, creado_en desc);

create table if not exists auditoria (
  id bigserial primary key,
  estudio_id uuid, usuario_id uuid, accion text not null, entidad text not null, entidad_id text,
  detalle jsonb, en timestamptz not null default now()
);

-- Row Level Security: la API usa la service key (no pasa por RLS) y controla el acceso por estudio;
-- RLS protege cualquier acceso directo con la anon key desde el navegador.
alter table estudios enable row level security;
alter table usuarios enable row level security;
alter table clientes enable row level security;
alter table usuarios_clientes enable row level security;
alter table archivos enable row level security;
alter table cierres enable row level security;
alter table auditoria enable row level security;

create or replace function public.puede_ver_cliente(p_cliente uuid) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from usuarios u join clientes c on c.estudio_id = u.estudio_id
    where u.id = auth.uid() and c.id = p_cliente
      and (u.rol <> 'socio_cliente'
           or exists (select 1 from usuarios_clientes uc where uc.usuario_id = u.id and uc.cliente_id = c.id))
  )
$$;

drop policy if exists usuarios_propio on usuarios;
create policy usuarios_propio on usuarios for select using (id = auth.uid());
drop policy if exists clientes_lectura on clientes;
create policy clientes_lectura on clientes for select using (public.puede_ver_cliente(id));
drop policy if exists archivos_lectura on archivos;
create policy archivos_lectura on archivos for select using (public.puede_ver_cliente(cliente_id));
drop policy if exists cierres_lectura on cierres;
create policy cierres_lectura on cierres for select using (public.puede_ver_cliente(cliente_id));

-- Bucket privado para archivos subidos y salidas (sólo existe en Supabase).
do $$ begin
  if exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    insert into storage.buckets (id, name, public) values ('control-gestion', 'control-gestion', false)
    on conflict (id) do nothing;
  end if;
end $$;
