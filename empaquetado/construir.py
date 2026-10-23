"""Creado con Claude. Construye el ejecutable con PyInstaller y lo comprime para distribuir.

Uso: ``uv run python empaquetado/construir.py``. El resultado queda en ``dist/``:
``Timetabling.app`` (macOS) o la carpeta ``Timetabling`` con ``Timetabling.exe`` (Windows),
más un ``.zip`` listo para copiar a otra computadora.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    subprocess.run([sys.executable, str(RAIZ / "empaquetado" / "generar_icono.py")], check=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(RAIZ / "dist"),
            "--workpath",
            str(RAIZ / "build"),
            str(RAIZ / "empaquetado" / "timetabling.spec"),
        ],
        check=True,
    )
    dist = RAIZ / "dist"
    if sys.platform == "darwin":
        origen = dist / "Timetabling.app"
        # La carpeta intermedia de COLLECT no se distribuye en macOS.
        shutil.rmtree(dist / "Timetabling", ignore_errors=True)
    else:
        origen = dist / "Timetabling"
    sistema = {"darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)
    nombre = dist / f"Timetabling-{sistema}-{platform.machine().lower()}"
    if sys.platform == "darwin":
        # ditto conserva enlaces simbólicos y permisos del paquete .app
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", str(origen), f"{nombre}.zip"], check=True
        )
    else:
        shutil.make_archive(str(nombre), "zip", dist, origen.name)
    print(f"Listo: {origen}\nArchivo para distribuir: {nombre}.zip")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
