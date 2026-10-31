"""Tests de la API contra un PostgreSQL real (local o el servicio de CI) y Storage en carpeta.

Variable TEST_DATABASE_URL: base vacía donde se aplica la migración de Supabase. Supabase trae el esquema
`auth` con auth.uid(); acá se crea uno mínimo para que la migración (RLS) se pueda aplicar igual.
"""
import os
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "web" / "backend"))

URL = os.environ.get("TEST_DATABASE_URL")
if not URL:
    pytest.skip("Definí TEST_DATABASE_URL para correr los tests de la API", allow_module_level=True)


@pytest.fixture(scope="session")
def app_cliente(tmp_path_factory):
    with psycopg.connect(URL, autocommit=True) as cx:
        cx.execute("drop schema public cascade; create schema public; drop schema if exists auth cascade;"
                   "create schema auth; create function auth.uid() returns uuid language sql as 'select null::uuid';")
        cx.execute((RAIZ / "supabase" / "migrations" / "20261031000000_fase1.sql").read_text())
    os.environ.update({"DATABASE_URL": URL, "AUTH_MODO": "dev", "STORAGE": "local",
                       "STORAGE_DIR": str(tmp_path_factory.mktemp("storage")),
                       "ADMIN_EMAILS": "admin@arfinance.test"})
    import importlib
    from app import config
    importlib.reload(config)
    config.ajustes.__init__()
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


ADMIN = {"X-Usuario-Dev": f"{uuid.uuid4()}|admin@arfinance.test"}


@pytest.fixture(scope="session")
def admin():
    return ADMIN
