"""Creado con Claude. El paquete no importa módulos de red ni olvida el encabezado."""

import ast
from pathlib import Path

PAQUETE = Path(__file__).parent.parent / "src" / "timetabling"
PROHIBIDOS = {"requests", "urllib.request", "http.client", "socket", "httpx", "urllib3"}


def _modulos_importados(ruta: Path) -> set[str]:
    arbol = ast.parse(ruta.read_text("utf-8"))
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos.add(nodo.module)
            modulos.update(f"{nodo.module}.{alias.name}" for alias in nodo.names)
    return modulos


def test_no_importa_modulos_de_red() -> None:
    for ruta in PAQUETE.rglob("*.py"):
        encontrados = {
            m
            for m in _modulos_importados(ruta)
            if any(m == p or m.startswith(p + ".") for p in PROHIBIDOS)
        }
        assert not encontrados, f"{ruta} importa {encontrados}"


def test_archivos_indican_que_fueron_creados_con_claude() -> None:
    for ruta in PAQUETE.rglob("*.py"):
        docstring = ast.get_docstring(ast.parse(ruta.read_text("utf-8")))
        assert docstring and docstring.startswith("Creado con Claude"), ruta
    readme = (PAQUETE.parent.parent / "README.md").read_text("utf-8").splitlines()
    assert readme[0].startswith("# ") and readme[2] == "Creado con Claude."
