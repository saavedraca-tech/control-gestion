# Puesta en línea (fases 0 y 1)

La plataforma usa tres servicios. Los tres tienen planes gratuitos para empezar:

| Servicio | Qué hace | Plan para empezar |
|---|---|---|
| **Supabase** | Base de datos, usuarios (login) y archivos | Free (después Pro, USD 25/mes, que incluye backups diarios) |
| **Render** | Corre la API y el motor de cierre (Python) | Starter, USD 7/mes (el plan gratis se "duerme" y tarda en despertar) |
| **Vercel** | Publica las pantallas (Next.js) | Hobby, gratis |

Configurarlo todo lleva entre 30 y 45 minutos. Seguí los pasos en orden.

---

## 1. Supabase (base, login y archivos)

1. En <https://supabase.com>, creá un proyecto **New project**:
   - **nombre:** `control-gestion`;
   - **región:** *South America (São Paulo)*;
   - anotá la contraseña de la base.
2. Andá a **SQL Editor › New query**, pegá el contenido de
   `supabase/migrations/20261031000000_fase1.sql` y apretá **Run**. Esto:
   - crea las tablas;
   - activa la seguridad por cliente (RLS);
   - crea el bucket privado `control-gestion`.
3. En **Authentication › Sign In / Providers**:
   - **Email** tiene que quedar activado;
   - **"Allow new users to sign up"** tiene que quedar **apagado**. Así solo entran las personas que invita el estudio.
4. Tomá tres datos de configuración:
   - **Project Settings › API:** `Project URL`, `anon public` y `service_role` (esta última es **secreta**);
   - **Project Settings › Database › Connection string › URI (Session pooler):** reemplazá `[YOUR-PASSWORD]` por la contraseña del paso 1.
5. En **Authentication › Users › Add user › Create new user**, creá tu usuario con tu email y una contraseña.

## 2. Render (API)

1. En <https://render.com>, andá a **New › Web Service** y conectá el repositorio de GitHub.
   - **Runtime:** Docker, con el `Dockerfile` de la raíz.
   - **Plan:** Starter.
2. En **Environment**, cargá las variables de `web/backend/.env.ejemplo`:

   | Variable | Valor |
   |---|---|
   | `DATABASE_URL` | La URI del paso 1.4 |
   | `SUPABASE_URL` | El Project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | La clave `service_role` |
   | `STORAGE` | `supabase` |
   | `AUTH_MODO` | `supabase` |
   | `ADMIN_EMAILS` | Tu email. Al entrar por primera vez, crea el estudio y te deja como administrador. |
   | `CORS_ORIGINS` | La dirección de Vercel (paso 3). Se completa después. |

3. Cuando termine el deploy, controlá que funcione: `https://TU-API.onrender.com/api/salud` tiene que responder `{"ok":true}`.

## 3. Vercel (pantallas)

1. En <https://vercel.com>, andá a **Add New › Project**, elegí el repositorio y en **Root Directory** poné `web/frontend`.
2. Cargá las variables de entorno:

   | Variable | Valor |
   |---|---|
   | `NEXT_PUBLIC_SUPABASE_URL` | El Project URL |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | La clave `anon public` (no es secreta) |
   | `NEXT_PUBLIC_API_URL` | `https://TU-API.onrender.com` |

3. Apretá **Deploy**. Después:
   - copiá la dirección (`https://algo.vercel.app`) en `CORS_ORIGINS` de Render;
   - en Supabase, cargala en **Authentication › URL Configuration › Site URL**.

## 4. Primer ingreso y migración de Duclos

1. Entrá a la dirección de Vercel con tu email y contraseña. Se crea el estudio y quedás como administrador.
2. Para pasar los clientes que hoy están en carpetas, con la configuración y todos sus archivos, corré una sola vez desde la computadora que tiene la carpeta `control-gestion`, con las variables del paso 2 en `web/backend/.env`:

   ```
   pip install -r web/backend/requirements.txt
   python web/backend/importar_clientes.py --email TU-EMAIL
   ```

   Otra opción: crear el cliente desde la web (**+ Nuevo cliente**) y subir los archivos arrastrándolos.
3. En la pantalla del cliente, elegí el mes y apretá **Cerrar el mes**:
   - el primer cierre de Duclos tarda alrededor de 1 minuto, porque lee todos los PDF;
   - los siguientes tardan segundos.

## 5. Dar acceso a otras personas

1. Creá la cuenta en Supabase: **Authentication › Users › Add user** (o **Invite**).
2. Asignale el rol con **SQL Editor**. Hasta la fase 2 se hace así; después habrá una pantalla para esto.

   ```sql
   -- Consultor del estudio (ve y procesa todos los clientes)
   insert into usuarios (id, estudio_id, email, rol)
   select u.id, (select id from estudios limit 1), u.email, 'consultor'
   from auth.users u where u.email = 'contadora@arfinance.com';

   -- Socio de un cliente (sólo ve su empresa y descarga tablero y PDF)
   insert into usuarios (id, estudio_id, email, rol)
   select u.id, (select id from estudios limit 1), u.email, 'socio_cliente'
   from auth.users u where u.email = 'socio@duclos.com';
   insert into usuarios_clientes (usuario_id, cliente_id)
   select u.id, c.id from auth.users u, clientes c where u.email = 'socio@duclos.com' and c.slug = 'duclos';
   ```

---

## Desarrollo local (sin Supabase)

```
docker compose up --build                  # PostgreSQL + API en http://localhost:8000 (login simulado)
cd web/frontend && npm install && npm run dev
```

**Tests:**

| Qué | Comando |
|---|---|
| Motor | `python -m pytest tests` |
| Ingesta | `python -m pytest web/backend/ingesta` |
| API (pide una base PostgreSQL vacía) | `TEST_DATABASE_URL=postgresql://... python -m pytest web/backend/tests` |

GitHub Actions (`.github/workflows/ci.yml`) corre todo esto en cada push.

## Privacidad

- **Los archivos reales de los clientes no van a GitHub.** `.gitignore` excluye `clientes/` y `referencia/`; esos datos viven solo en Supabase.
- **La clave `service_role`** está solo en Render. Nunca se pone en Vercel ni en el código.
- **Lo que ve cada usuario:**
  - los socios solo ven sus empresas;
  - los consultores ven todo el estudio;
  - cada acción queda registrada en la tabla `auditoria`.

## Limitaciones de la fase 1 (se resuelven en las fases siguientes)

- **Decisiones de la reunión:** las ediciones de la hoja *Decisiones* hechas en el Excel descargado no vuelven a la web. Se pasan a una pantalla en la fase 2.
- **Reglas y metas:** se editan con la API (`PUT /api/clientes/{id}/config`) o volviendo a importar el YAML. La pantalla para editarlas llega en la fase 2.
- **Cola de cierres:** los cierres corren dentro del proceso de la API. Alcanza para un estudio; con muchos cierres simultáneos conviene un *worker* aparte (fase 6).
