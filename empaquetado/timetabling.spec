# Creado con Claude. Especificación de PyInstaller para Timetabling.
# Construir con:  uv run python empaquetado/construir.py
# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

RAIZ = Path(SPECPATH).parent  # noqa: F821 - variable que define PyInstaller
FUENTES = RAIZ / "src"

datas = [
    (str(FUENTES / "timetabling" / "persistencia" / "esquema.sql"), "timetabling/persistencia"),
    (str(FUENTES / "timetabling" / "recursos" / "icono.png"), "timetabling/recursos"),
]
binaries = []
hiddenimports = []
# OR-Tools no trae hook de PyInstaller: se recogen sus módulos y bibliotecas nativas.
for paquete in ("ortools",):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(Path(SPECPATH) / "lanzador.py")],  # noqa: F821
    pathex=[str(FUENTES)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "tkinter", "matplotlib", "IPython", "pytest", "openpyxl",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

icono = str(Path(SPECPATH) / ("icono.icns" if sys.platform == "darwin" else "icono.ico"))  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Timetabling",
    console=False,  # aplicación de ventana (sin consola en Windows)
    icon=icono,
    upx=False,
)
coleccion = COLLECT(exe, a.binaries, a.datas, name="Timetabling", upx=False)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coleccion,
        name="Timetabling.app",
        icon=icono,
        bundle_identifier="local.timetabling",
        info_plist={
            "CFBundleDisplayName": "Timetabling",
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.education",
        },
    )
