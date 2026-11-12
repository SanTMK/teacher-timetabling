"""Creado con Claude. Versionado y migración del esquema de los proyectos ``.horario``.

Cada migración lleva un proyecto de la versión ``n - 1`` a la versión ``n``. Para
cambiar el esquema: actualizar ``esquema.sql`` (proyectos nuevos), incrementar
``VERSION_ACTUAL`` y registrar la función correspondiente en ``MIGRACIONES``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from importlib import resources

VERSION_ACTUAL = 5

Migracion = Callable[[sqlite3.Connection], None]


def _a_v2(conexion: sqlite3.Connection) -> None:
    """Duraciones especiales por hora (p. ej. una última hora más corta)."""
    conexion.execute(
        "ALTER TABLE niveles ADD COLUMN duraciones_especiales TEXT NOT NULL DEFAULT '{}'"
    )


def _a_v3(conexion: sqlite3.Connection) -> None:
    """Profesor fijo por grupo y asignatura."""
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS docentes_asignados ("
        " grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,"
        " asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,"
        " profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,"
        " PRIMARY KEY (grupo_id, asignatura_id))"
    )


def _a_v4(conexion: sqlite3.Connection) -> None:
    """Eventos por nivel (hora cívica) y profesores que asisten a ellos."""
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS eventos ("
        " id INTEGER PRIMARY KEY,"
        " nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,"
        " nombre TEXT NOT NULL, dia TEXT NOT NULL,"
        " inicio INTEGER NOT NULL, fin INTEGER NOT NULL)"
    )
    conexion.execute(
        "CREATE TABLE IF NOT EXISTS profesor_evento ("
        " profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,"
        " evento_id INTEGER NOT NULL REFERENCES eventos(id) ON DELETE CASCADE,"
        " PRIMARY KEY (profesor_id, evento_id))"
    )


def _a_v5(conexion: sqlite3.Connection) -> None:
    """Marca de la solución vigente (el horario que está en uso)."""
    columnas = {fila[1] for fila in conexion.execute("PRAGMA table_info(soluciones)")}
    if "vigente" not in columnas:
        conexion.execute("ALTER TABLE soluciones ADD COLUMN vigente INTEGER NOT NULL DEFAULT 0")


# versión destino → función que migra desde la versión anterior
MIGRACIONES: dict[int, Migracion] = {2: _a_v2, 3: _a_v3, 4: _a_v4, 5: _a_v5}


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
