"""Creado con Claude. Única puerta de acceso a la base de datos SQLite de un proyecto.

Convierte filas SQLite ↔ objetos del dominio. Carga un ``DatosEscuela`` completo para
el núcleo y ofrece altas, bajas y modificaciones para la interfaz.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType

from timetabling.dominio.modelos import (
    Asignacion,
    AsignacionFija,
    Asignatura,
    Configuracion,
    DatosEscuela,
    Disponibilidad,
    Espacio,
    EstadoSolucion,
    Grado,
    Grupo,
    Nivel,
    Pesos,
    PlanEstudios,
    Profesor,
    Receso,
    Solucion,
)
from timetabling.persistencia.migraciones import aplicar_migraciones

EXTENSION = ".horario"


class Repositorio:
    """Proyecto de horario abierto. Usar ``Repositorio.crear`` o ``Repositorio.abrir``."""

    def __init__(self, ruta: Path, conexion: sqlite3.Connection) -> None:
        self.ruta = ruta
        self._cx = conexion

    # --- Ciclo de vida --------------------------------------------------------------

    @staticmethod
    def _conectar(ruta: Path) -> sqlite3.Connection:
        conexion = sqlite3.connect(ruta)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        return conexion

    @classmethod
    def crear(cls, ruta: str | Path, sobrescribir: bool = False) -> Repositorio:
        """Crea un proyecto nuevo con la configuración por defecto."""
        ruta = Path(ruta)
        if ruta.exists():
            if not sobrescribir:
                raise FileExistsError(f"Ya existe el archivo {ruta}")
            ruta.unlink()
        conexion = cls._conectar(ruta)
        aplicar_migraciones(conexion)
        repo = cls(ruta, conexion)
        repo.guardar_configuracion(Configuracion())
        return repo

    @classmethod
    def abrir(cls, ruta: str | Path) -> Repositorio:
        """Abre un proyecto existente y lo migra a la versión actual si hace falta."""
        ruta = Path(ruta)
        if not ruta.exists():
            raise FileNotFoundError(f"No existe el proyecto {ruta}")
        conexion = cls._conectar(ruta)
        try:
            aplicar_migraciones(conexion)
        except Exception:
            conexion.close()
            raise
        repo = cls(ruta, conexion)
        if conexion.execute("SELECT 1 FROM configuracion").fetchone() is None:
            repo.guardar_configuracion(Configuracion())
        return repo

    def cerrar(self) -> None:
        self._cx.close()

    def __enter__(self) -> Repositorio:
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        valor: BaseException | None,
        traza: TracebackType | None,
    ) -> None:
        self.cerrar()

    def guardar_como(self, destino: str | Path) -> None:
        """Copia el proyecto completo a otro archivo (respaldo / «Guardar como»)."""
        destino = Path(destino)
        if destino.exists():
            destino.unlink()
        copia = sqlite3.connect(destino)
        try:
            self._cx.backup(copia)
        finally:
            copia.close()

    def _ejecutar(self, sql: str, parametros: tuple[object, ...] = ()) -> sqlite3.Cursor:
        return self._cx.execute(sql, parametros)

    def _filas(self, sql: str, parametros: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return self._cx.execute(sql, parametros).fetchall()

    # --- Carga completa -------------------------------------------------------------

    def cargar_datos(self) -> DatosEscuela:
        return DatosEscuela(
            configuracion=self.obtener_configuracion(),
            niveles=self.listar_niveles(),
            grados=self.listar_grados(),
            grupos=self.listar_grupos(),
            asignaturas=self.listar_asignaturas(),
            plan=self.listar_plan(),
            profesores=self.listar_profesores(),
            espacios=self.listar_espacios(),
            asignaciones_fijas=self.listar_asignaciones_fijas(),
        )

    def reemplazar_datos(self, datos: DatosEscuela) -> None:
        """Sustituye todos los datos de captura del proyecto (conserva los ids dados).

        Las soluciones guardadas se eliminan porque dejarían de corresponder a los datos.
        """
        with self._cx:
            for tabla in (
                "soluciones",
                "asignaciones_fijas",
                "plan_estudios",
                "grupos",
                "profesores",
                "grados",
                "niveles",
                "asignaturas",
                "espacios",
            ):
                self._ejecutar(f"DELETE FROM {tabla}")
        self.guardar_configuracion(datos.configuracion)
        for nivel in datos.niveles:
            self.guardar_nivel(nivel)
        for grado in datos.grados:
            self.guardar_grado(grado)
        for asignatura in datos.asignaturas:
            self.guardar_asignatura(asignatura)
        for profesor in datos.profesores:
            self.guardar_profesor(profesor)
        for grupo in datos.grupos:
            self.guardar_grupo(grupo)
        for item in datos.plan:
            self.guardar_plan(item)
        for espacio in datos.espacios:
            self.guardar_espacio(espacio)
        for fija in datos.asignaciones_fijas:
            self.guardar_asignacion_fija(fija)

    def _guardar(self, tabla: str, campos: dict[str, object], id_: int | None) -> int:
        """Inserta (o actualiza si el id existe) y devuelve el id."""
        if id_ is not None:
            existe = self._ejecutar(f"SELECT 1 FROM {tabla} WHERE id = ?", (id_,)).fetchone()
            if existe:
                asignaciones = ", ".join(f"{c} = ?" for c in campos)
                self._ejecutar(
                    f"UPDATE {tabla} SET {asignaciones} WHERE id = ?", (*campos.values(), id_)
                )
                return id_
            campos = {"id": id_, **campos}
        columnas = ", ".join(campos)
        marcas = ", ".join("?" for _ in campos)
        cursor = self._ejecutar(
            f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})", tuple(campos.values())
        )
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def _eliminar(self, tabla: str, id_: int) -> None:
        with self._cx:
            self._ejecutar(f"DELETE FROM {tabla} WHERE id = ?", (id_,))

    # --- Configuración --------------------------------------------------------------

    def obtener_configuracion(self) -> Configuracion:
        fila = self._ejecutar("SELECT * FROM configuracion WHERE id = 1").fetchone()
        if fila is None:
            return Configuracion()
        return Configuracion(
            nombre_escuela=fila["nombre_escuela"],
            margen_traslado_min=fila["margen_traslado_min"],
            tiempo_limite_s=fila["tiempo_limite_s"],
            hilos=fila["hilos"],
            pesos=Pesos.model_validate(json.loads(fila["pesos"])),
        )

    def guardar_configuracion(self, config: Configuracion) -> None:
        with self._cx:
            self._ejecutar(
                "INSERT OR REPLACE INTO configuracion "
                "(id, nombre_escuela, margen_traslado_min, tiempo_limite_s, hilos, pesos) "
                "VALUES (1, ?, ?, ?, ?, ?)",
                (
                    config.nombre_escuela,
                    config.margen_traslado_min,
                    config.tiempo_limite_s,
                    config.hilos,
                    config.pesos.model_dump_json(),
                ),
            )

    # --- Niveles y recesos ----------------------------------------------------------

    def listar_niveles(self) -> list[Nivel]:
        recesos: dict[int, list[Receso]] = {}
        for fila in self._filas("SELECT * FROM recesos ORDER BY inicio, id"):
            recesos.setdefault(fila["nivel_id"], []).append(
                Receso(
                    id=fila["id"],
                    nivel_id=fila["nivel_id"],
                    nombre=fila["nombre"],
                    inicio=fila["inicio"],
                    fin=fila["fin"],
                )
            )
        return [
            Nivel(
                id=f["id"],
                nombre=f["nombre"],
                duracion_min=f["duracion_min"],
                inicio_jornada=f["inicio_jornada"],
                fin_jornada=f["fin_jornada"],
                dias=f["dias"].split(","),
                recesos=recesos.get(f["id"], []),
                sin_huecos_alumnos=bool(f["sin_huecos_alumnos"]),
            )
            for f in self._filas("SELECT * FROM niveles ORDER BY id")
        ]

    def guardar_nivel(self, nivel: Nivel) -> Nivel:
        """Guarda el nivel y reemplaza sus recesos. Devuelve el nivel con ids asignados."""
        with self._cx:
            id_ = self._guardar(
                "niveles",
                {
                    "nombre": nivel.nombre,
                    "duracion_min": nivel.duracion_min,
                    "inicio_jornada": nivel.inicio_jornada,
                    "fin_jornada": nivel.fin_jornada,
                    "dias": ",".join(nivel.dias),
                    "sin_huecos_alumnos": int(nivel.sin_huecos_alumnos),
                },
                nivel.id,
            )
            self._ejecutar("DELETE FROM recesos WHERE nivel_id = ?", (id_,))
            recesos = []
            for receso in nivel.recesos:
                rid = self._guardar(
                    "recesos",
                    {
                        "nivel_id": id_,
                        "nombre": receso.nombre,
                        "inicio": receso.inicio,
                        "fin": receso.fin,
                    },
                    receso.id,
                )
                recesos.append(receso.model_copy(update={"id": rid, "nivel_id": id_}))
        return nivel.model_copy(update={"id": id_, "recesos": recesos})

    def eliminar_nivel(self, nivel_id: int) -> None:
        self._eliminar("niveles", nivel_id)

    # --- Grados y grupos ------------------------------------------------------------

    def listar_grados(self) -> list[Grado]:
        return [
            Grado(id=f["id"], nivel_id=f["nivel_id"], nombre=f["nombre"])
            for f in self._filas("SELECT * FROM grados ORDER BY nivel_id, id")
        ]

    def guardar_grado(self, grado: Grado) -> Grado:
        with self._cx:
            id_ = self._guardar(
                "grados", {"nivel_id": grado.nivel_id, "nombre": grado.nombre}, grado.id
            )
        return grado.model_copy(update={"id": id_})

    def eliminar_grado(self, grado_id: int) -> None:
        self._eliminar("grados", grado_id)

    def listar_grupos(self) -> list[Grupo]:
        return [
            Grupo(
                id=f["id"],
                grado_id=f["grado_id"],
                seccion=f["seccion"],
                estudiantes=f["estudiantes"],
                titular_id=f["titular_id"],
            )
            for f in self._filas("SELECT * FROM grupos ORDER BY grado_id, seccion, id")
        ]

    def guardar_grupo(self, grupo: Grupo) -> Grupo:
        with self._cx:
            id_ = self._guardar(
                "grupos",
                {
                    "grado_id": grupo.grado_id,
                    "seccion": grupo.seccion,
                    "estudiantes": grupo.estudiantes,
                    "titular_id": grupo.titular_id,
                },
                grupo.id,
            )
        return grupo.model_copy(update={"id": id_})

    def eliminar_grupo(self, grupo_id: int) -> None:
        self._eliminar("grupos", grupo_id)

    # --- Asignaturas y plan de estudios ---------------------------------------------

    def listar_asignaturas(self) -> list[Asignatura]:
        return [
            Asignatura(
                id=f["id"],
                nombre=f["nombre"],
                espacio_requerido=f["espacio_requerido"],
                max_horas_dia=f["max_horas_dia"],
                bloque_doble=f["bloque_doble"],
                exigente=bool(f["exigente"]),
                color=f["color"],
            )
            for f in self._filas("SELECT * FROM asignaturas ORDER BY id")
        ]

    def guardar_asignatura(self, asignatura: Asignatura) -> Asignatura:
        with self._cx:
            id_ = self._guardar(
                "asignaturas",
                {
                    "nombre": asignatura.nombre,
                    "espacio_requerido": asignatura.espacio_requerido,
                    "max_horas_dia": asignatura.max_horas_dia,
                    "bloque_doble": asignatura.bloque_doble.value,
                    "exigente": int(asignatura.exigente),
                    "color": asignatura.color,
                },
                asignatura.id,
            )
        return asignatura.model_copy(update={"id": id_})

    def eliminar_asignatura(self, asignatura_id: int) -> None:
        self._eliminar("asignaturas", asignatura_id)

    def listar_plan(self) -> list[PlanEstudios]:
        return [
            PlanEstudios(
                grado_id=f["grado_id"],
                asignatura_id=f["asignatura_id"],
                horas_semanales=f["horas_semanales"],
            )
            for f in self._filas("SELECT * FROM plan_estudios ORDER BY grado_id, asignatura_id")
        ]

    def guardar_plan(self, item: PlanEstudios) -> None:
        """Fija las horas semanales de una asignatura en un grado (0 la quita del plan)."""
        with self._cx:
            if item.horas_semanales == 0:
                self._ejecutar(
                    "DELETE FROM plan_estudios WHERE grado_id = ? AND asignatura_id = ?",
                    (item.grado_id, item.asignatura_id),
                )
            else:
                self._ejecutar(
                    "INSERT OR REPLACE INTO plan_estudios "
                    "(grado_id, asignatura_id, horas_semanales) VALUES (?, ?, ?)",
                    (item.grado_id, item.asignatura_id, item.horas_semanales),
                )

    # --- Profesores -----------------------------------------------------------------

    def listar_profesores(self) -> list[Profesor]:
        asignaturas: dict[int, set[int]] = {}
        for f in self._filas("SELECT * FROM profesor_asignatura"):
            asignaturas.setdefault(f["profesor_id"], set()).add(f["asignatura_id"])
        grados: dict[int, set[int]] = {}
        for f in self._filas("SELECT * FROM profesor_grado"):
            grados.setdefault(f["profesor_id"], set()).add(f["grado_id"])
        disponibilidad: dict[int, list[Disponibilidad]] = {}
        for f in self._filas("SELECT * FROM disponibilidad ORDER BY id"):
            disponibilidad.setdefault(f["profesor_id"], []).append(
                Disponibilidad(
                    id=f["id"], dia=f["dia"], inicio=f["inicio"], fin=f["fin"], tipo=f["tipo"]
                )
            )
        return [
            Profesor(
                id=f["id"],
                nombre=f["nombre"],
                asignaturas=asignaturas.get(f["id"], set()),
                grados=grados.get(f["id"], set()),
                disponibilidad=disponibilidad.get(f["id"], []),
                carga_max_semanal_min=f["carga_max_semanal_min"],
                carga_max_diaria_min=f["carga_max_diaria_min"],
                max_consecutivas=f["max_consecutivas"],
            )
            for f in self._filas("SELECT * FROM profesores ORDER BY id")
        ]

    def guardar_profesor(self, profesor: Profesor) -> Profesor:
        """Guarda el profesor con sus asignaturas, grados y disponibilidad."""
        with self._cx:
            id_ = self._guardar(
                "profesores",
                {
                    "nombre": profesor.nombre,
                    "carga_max_semanal_min": profesor.carga_max_semanal_min,
                    "carga_max_diaria_min": profesor.carga_max_diaria_min,
                    "max_consecutivas": profesor.max_consecutivas,
                },
                profesor.id,
            )
            self._ejecutar("DELETE FROM profesor_asignatura WHERE profesor_id = ?", (id_,))
            self._cx.executemany(
                "INSERT INTO profesor_asignatura (profesor_id, asignatura_id) VALUES (?, ?)",
                [(id_, a) for a in sorted(profesor.asignaturas)],
            )
            self._ejecutar("DELETE FROM profesor_grado WHERE profesor_id = ?", (id_,))
            self._cx.executemany(
                "INSERT INTO profesor_grado (profesor_id, grado_id) VALUES (?, ?)",
                [(id_, g) for g in sorted(profesor.grados)],
            )
            self._ejecutar("DELETE FROM disponibilidad WHERE profesor_id = ?", (id_,))
            disponibilidad = []
            for d in profesor.disponibilidad:
                did = self._guardar(
                    "disponibilidad",
                    {
                        "profesor_id": id_,
                        "dia": d.dia,
                        "inicio": d.inicio,
                        "fin": d.fin,
                        "tipo": d.tipo.value,
                    },
                    d.id,
                )
                disponibilidad.append(d.model_copy(update={"id": did}))
        return profesor.model_copy(update={"id": id_, "disponibilidad": disponibilidad})

    def eliminar_profesor(self, profesor_id: int) -> None:
        self._eliminar("profesores", profesor_id)

    # --- Espacios y asignaciones fijas ----------------------------------------------

    def listar_espacios(self) -> list[Espacio]:
        return [
            Espacio(id=f["id"], nombre=f["nombre"], tipo=f["tipo"], cantidad=f["cantidad"])
            for f in self._filas("SELECT * FROM espacios ORDER BY id")
        ]

    def guardar_espacio(self, espacio: Espacio) -> Espacio:
        with self._cx:
            id_ = self._guardar(
                "espacios",
                {"nombre": espacio.nombre, "tipo": espacio.tipo, "cantidad": espacio.cantidad},
                espacio.id,
            )
        return espacio.model_copy(update={"id": id_})

    def eliminar_espacio(self, espacio_id: int) -> None:
        self._eliminar("espacios", espacio_id)

    def listar_asignaciones_fijas(self) -> list[AsignacionFija]:
        return [
            AsignacionFija(
                id=f["id"],
                grupo_id=f["grupo_id"],
                asignatura_id=f["asignatura_id"],
                profesor_id=f["profesor_id"],
                dia=f["dia"],
                indice_franja=f["indice_franja"],
            )
            for f in self._filas("SELECT * FROM asignaciones_fijas ORDER BY id")
        ]

    def guardar_asignacion_fija(self, fija: AsignacionFija) -> AsignacionFija:
        with self._cx:
            id_ = self._guardar(
                "asignaciones_fijas",
                {
                    "grupo_id": fija.grupo_id,
                    "asignatura_id": fija.asignatura_id,
                    "profesor_id": fija.profesor_id,
                    "dia": fija.dia,
                    "indice_franja": fija.indice_franja,
                },
                fija.id,
            )
        return fija.model_copy(update={"id": id_})

    def eliminar_asignacion_fija(self, fija_id: int) -> None:
        self._eliminar("asignaciones_fijas", fija_id)

    # --- Impacto de un borrado ------------------------------------------------------

    _DEPENDENCIAS: dict[str, list[tuple[str, str]]] = {
        "niveles": [
            ("grados", "SELECT COUNT(*) FROM grados WHERE nivel_id = ?"),
            (
                "grupos",
                "SELECT COUNT(*) FROM grupos g JOIN grados d ON g.grado_id = d.id "
                "WHERE d.nivel_id = ?",
            ),
            (
                "soluciones",
                "SELECT COUNT(DISTINCT solucion_id) FROM asignaciones WHERE nivel_id = ?",
            ),
        ],
        "grados": [
            ("grupos", "SELECT COUNT(*) FROM grupos WHERE grado_id = ?"),
            ("plan de estudios", "SELECT COUNT(*) FROM plan_estudios WHERE grado_id = ?"),
        ],
        "grupos": [
            ("asignaciones fijas", "SELECT COUNT(*) FROM asignaciones_fijas WHERE grupo_id = ?"),
            (
                "soluciones",
                "SELECT COUNT(DISTINCT solucion_id) FROM asignaciones WHERE grupo_id = ?",
            ),
        ],
        "asignaturas": [
            ("plan de estudios", "SELECT COUNT(*) FROM plan_estudios WHERE asignatura_id = ?"),
            ("profesores", "SELECT COUNT(*) FROM profesor_asignatura WHERE asignatura_id = ?"),
            (
                "asignaciones fijas",
                "SELECT COUNT(*) FROM asignaciones_fijas WHERE asignatura_id = ?",
            ),
            (
                "soluciones",
                "SELECT COUNT(DISTINCT solucion_id) FROM asignaciones WHERE asignatura_id = ?",
            ),
        ],
        "profesores": [
            ("disponibilidad", "SELECT COUNT(*) FROM disponibilidad WHERE profesor_id = ?"),
            ("grupos con titular", "SELECT COUNT(*) FROM grupos WHERE titular_id = ?"),
            (
                "asignaciones fijas",
                "SELECT COUNT(*) FROM asignaciones_fijas WHERE profesor_id = ?",
            ),
            (
                "soluciones",
                "SELECT COUNT(DISTINCT solucion_id) FROM asignaciones WHERE profesor_id = ?",
            ),
        ],
    }

    def afectados_por_eliminar(self, tabla: str, id_: int) -> dict[str, int]:
        """Qué se verá afectado (y cuántos elementos) si se borra ``tabla[id_]``."""
        afectados: dict[str, int] = {}
        for nombre, sql in self._DEPENDENCIAS.get(tabla, []):
            cuenta = self._ejecutar(sql, (id_,)).fetchone()[0]
            if cuenta:
                afectados[nombre] = cuenta
        return afectados

    # --- Soluciones -----------------------------------------------------------------

    def guardar_solucion(self, solucion: Solucion) -> Solucion:
        with self._cx:
            cursor = self._ejecutar(
                "INSERT INTO soluciones (fecha, estado, tiempo_s, penalizaciones, nota) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    solucion.fecha.isoformat(),
                    solucion.estado.value,
                    solucion.tiempo_s,
                    json.dumps(solucion.penalizaciones),
                    solucion.nota,
                ),
            )
            sid = cursor.lastrowid
            assert sid is not None
            self._cx.executemany(
                "INSERT INTO asignaciones "
                "(solucion_id, grupo_id, asignatura_id, profesor_id, nivel_id, dia, indice) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (sid, a.grupo_id, a.asignatura_id, a.profesor_id, a.nivel_id, a.dia, a.indice)
                    for a in solucion.asignaciones
                ],
            )
        return solucion.model_copy(
            update={
                "id": sid,
                "asignaciones": [
                    a.model_copy(update={"solucion_id": sid}) for a in solucion.asignaciones
                ],
            }
        )

    def _solucion_de_fila(self, fila: sqlite3.Row, asignaciones: list[Asignacion]) -> Solucion:
        return Solucion(
            id=fila["id"],
            fecha=datetime.fromisoformat(fila["fecha"]),
            estado=EstadoSolucion(fila["estado"]),
            tiempo_s=fila["tiempo_s"],
            penalizaciones=json.loads(fila["penalizaciones"]),
            nota=fila["nota"],
            asignaciones=asignaciones,
        )

    def listar_soluciones(self) -> list[Solucion]:
        """Soluciones guardadas, sin sus asignaciones (para selectores)."""
        return [
            self._solucion_de_fila(f, [])
            for f in self._filas("SELECT * FROM soluciones ORDER BY id DESC")
        ]

    def cargar_solucion(self, solucion_id: int) -> Solucion:
        fila = self._ejecutar("SELECT * FROM soluciones WHERE id = ?", (solucion_id,)).fetchone()
        if fila is None:
            raise KeyError(f"No existe la solución {solucion_id}")
        asignaciones = [
            Asignacion(
                solucion_id=f["solucion_id"],
                grupo_id=f["grupo_id"],
                asignatura_id=f["asignatura_id"],
                profesor_id=f["profesor_id"],
                nivel_id=f["nivel_id"],
                dia=f["dia"],
                indice=f["indice"],
            )
            for f in self._filas(
                "SELECT * FROM asignaciones WHERE solucion_id = ? ORDER BY id", (solucion_id,)
            )
        ]
        return self._solucion_de_fila(fila, asignaciones)

    def actualizar_nota_solucion(self, solucion_id: int, nota: str) -> None:
        with self._cx:
            self._ejecutar("UPDATE soluciones SET nota = ? WHERE id = ?", (nota, solucion_id))

    def eliminar_solucion(self, solucion_id: int) -> None:
        self._eliminar("soluciones", solucion_id)
