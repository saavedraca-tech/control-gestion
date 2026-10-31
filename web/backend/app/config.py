"""Configuración por variables de entorno (ver web/.env.ejemplo)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]   # carpeta control-gestion (contiene src/ y plantillas_rubro/)


@dataclass
class Ajustes:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", "").rstrip("/"))
    supabase_service_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    bucket: str = field(default_factory=lambda: os.environ.get("STORAGE_BUCKET", "control-gestion"))
    # "supabase" en producción; "local" guarda en una carpeta (desarrollo y tests)
    storage: str = field(default_factory=lambda: os.environ.get("STORAGE", "supabase"))
    storage_dir: str = field(default_factory=lambda: os.environ.get("STORAGE_DIR", "/tmp/cg-storage"))
    # "supabase" valida el token contra Supabase Auth; "dev" acepta el header X-Usuario-Dev (sólo local)
    auth: str = field(default_factory=lambda: os.environ.get("AUTH_MODO", "supabase"))
    # Emails que, al entrar por primera vez, crean el estudio y quedan como administradores
    admin_emails: list = field(default_factory=lambda: [e.strip().lower() for e in
                                                        os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()])
    nombre_estudio: str = field(default_factory=lambda: os.environ.get("NOMBRE_ESTUDIO", "ARFinance"))
    cors_origins: list = field(default_factory=lambda: [o.strip() for o in
                                                        os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")])
    max_mb: int = field(default_factory=lambda: int(os.environ.get("MAX_MB_ARCHIVO", "25")))


ajustes = Ajustes()
