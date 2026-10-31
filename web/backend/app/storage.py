"""Almacenamiento de archivos: Supabase Storage (bucket privado) o carpeta local (desarrollo y tests)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx

from .config import ajustes


class StorageLocal:
    def __init__(self, raiz: str):
        self.raiz = Path(raiz)

    def _p(self, ruta: str) -> Path:
        p = (self.raiz / ruta).resolve()
        if self.raiz.resolve() not in p.parents:
            raise ValueError("ruta inválida")
        return p

    def subir(self, ruta: str, contenido: bytes, tipo: str = "application/octet-stream") -> None:
        p = self._p(ruta)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(contenido)

    def bajar(self, ruta: str) -> bytes:
        return self._p(ruta).read_bytes()

    def existe(self, ruta: str) -> bool:
        return self._p(ruta).exists()

    def borrar(self, ruta: str) -> None:
        p = self._p(ruta)
        if p.exists():
            p.unlink()

    def listar(self, prefijo: str) -> list[str]:
        base = self._p(prefijo) if prefijo else self.raiz
        if not base.is_dir():
            return []
        return [str(p.relative_to(self.raiz)) for p in base.rglob("*") if p.is_file()]


class StorageSupabase:
    def __init__(self, url: str, key: str, bucket: str):
        self.base = f"{url}/storage/v1"
        self.bucket = bucket
        self.h = {"Authorization": f"Bearer {key}", "apikey": key}

    def _url(self, ruta: str) -> str:
        return f"{self.base}/object/{self.bucket}/{quote(ruta)}"

    def subir(self, ruta: str, contenido: bytes, tipo: str = "application/octet-stream") -> None:
        r = httpx.post(self._url(ruta), content=contenido, timeout=120,
                       headers={**self.h, "Content-Type": tipo, "x-upsert": "true"})
        r.raise_for_status()

    def bajar(self, ruta: str) -> bytes:
        r = httpx.get(self._url(ruta), headers=self.h, timeout=120)
        r.raise_for_status()
        return r.content

    def existe(self, ruta: str) -> bool:
        return httpx.head(self._url(ruta), headers=self.h, timeout=30).status_code == 200

    def borrar(self, ruta: str) -> None:
        httpx.request("DELETE", f"{self.base}/object/{self.bucket}", headers=self.h,
                      json={"prefixes": [ruta]}, timeout=30)

    def listar(self, prefijo: str) -> list[str]:
        """Lista recursivamente (la API de Supabase devuelve un nivel por llamada)."""
        out, pendientes = [], [prefijo.rstrip("/")]
        while pendientes:
            carpeta = pendientes.pop()
            r = httpx.post(f"{self.base}/object/list/{self.bucket}", headers=self.h, timeout=30,
                           json={"prefix": carpeta, "limit": 1000, "offset": 0})
            r.raise_for_status()
            for it in r.json():
                ruta = f"{carpeta}/{it['name']}" if carpeta else it["name"]
                (out.append(ruta) if it.get("id") else pendientes.append(ruta))
        return out


def storage():
    if ajustes.storage == "local":
        return StorageLocal(ajustes.storage_dir)
    return StorageSupabase(ajustes.supabase_url, ajustes.supabase_service_key, ajustes.bucket)
