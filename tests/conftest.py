import shutil
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "tests"))


def copiar_base(destino: Path, clientes=()) -> Path:
    """Copia plantillas (y los clientes pedidos, sin sus salidas) a una base temporal."""
    shutil.copytree(RAIZ / "plantillas_rubro", destino / "plantillas_rubro")
    for c in clientes:
        src = RAIZ / "clientes" / c
        shutil.copytree(src / "config", destino / "clientes" / c / "config")
        shutil.copytree(src / "entrada", destino / "clientes" / c / "entrada")
    return destino


@pytest.fixture(scope="session")
def base_duclos(tmp_path_factory):
    if not (RAIZ / "clientes" / "duclos" / "entrada").is_dir():
        pytest.skip("Faltan los archivos de Duclos")
    return copiar_base(tmp_path_factory.mktemp("base_duclos"), ["duclos"])


@pytest.fixture(scope="session")
def duclos(base_duclos):
    """Cliente Duclos cargado, con el contexto armado a octubre 2026."""
    from src import contexto, historico
    from src.config import cargar_cliente
    c = cargar_cliente(base_duclos, "duclos")
    carga = historico.cargar(c)
    ctx = contexto.construir(c, carga.base, "2026-10")
    return {"c": c, "carga": carga, "ctx": ctx, "base": base_duclos}
