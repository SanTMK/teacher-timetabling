"""Creado con Claude. Versionado y migración del esquema de los proyectos ``.horario``.

Cada migración lleva un proyecto de la versión ``n - 1`` a la versión ``n``. Para
cambiar el esquema: actualizar ``esquema.sql`` (proyectos nuevos), incrementar
``VERSION_ACTUAL`` y registrar la función correspondiente en ``MIGRACIONES``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from importlib import resources

VERSION_ACTUAL = 1

Migracion = Callable[[sqlite3.Connection], None]

# versión destino → función que migra desde la versión anterior
MIGRACIONES: dict[int, Migracion] = {}


class ErrorVersionEsquema(Exception):
    """El proyecto fue creado con una versión más nueva del programa."""


def leer_esquema() -> str:
    return resources.files("timetabling.persistencia").joinpath("esquema.sql").read_text("utf-8")


def version_de(conexion: sqlite3.Connection) -> int | None:
    existe = conexion.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'esquema_version'"
    ).fetchone()
    if not existe:
        return None
    fila = conexion.execute("SELECT version FROM esquema_version").fetchone()
    return int(fila[0]) if fila else None


def crear_esquema(conexion: sqlite3.Connection) -> None:
    conexion.executescript(leer_esquema())
    conexion.execute("INSERT INTO esquema_version (version) VALUES (?)", (VERSION_ACTUAL,))
    conexion.commit()


def aplicar_migraciones(
    conexion: sqlite3.Connection,
    version_actual: int = VERSION_ACTUAL,
    migraciones: dict[int, Migracion] | None = None,
) -> int:
    """Crea el esquema si la base está vacía o la migra hasta ``version_actual``.

    Devuelve la versión anterior (``0`` si la base estaba vacía).
    """
    migraciones = MIGRACIONES if migraciones is None else migraciones
    version = version_de(conexion)
    if version is None:
        crear_esquema(conexion)
        return 0
    if version > version_actual:
        raise ErrorVersionEsquema(
            f"El proyecto usa el esquema versión {version}, pero este programa solo conoce "
            f"hasta la {version_actual}. Actualice el programa para abrirlo."
        )
    for destino in range(version + 1, version_actual + 1):
        try:
            migraciones[destino](conexion)
            conexion.execute("UPDATE esquema_version SET version = ?", (destino,))
            conexion.commit()
        except Exception:
            conexion.rollback()
            raise
    return version
