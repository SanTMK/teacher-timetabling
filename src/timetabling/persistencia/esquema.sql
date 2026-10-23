-- Creado con Claude. Esquema SQLite de un proyecto de horario (versión 1).

CREATE TABLE esquema_version (
    version INTEGER NOT NULL
);

CREATE TABLE configuracion (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    nombre_escuela TEXT NOT NULL,
    margen_traslado_min INTEGER NOT NULL,
    tiempo_limite_s INTEGER NOT NULL,
    hilos INTEGER NOT NULL,
    pesos TEXT NOT NULL  -- JSON con los pesos de las restricciones blandas
);

CREATE TABLE niveles (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    duracion_min INTEGER NOT NULL,
    inicio_jornada INTEGER NOT NULL,
    fin_jornada INTEGER NOT NULL,
    dias TEXT NOT NULL,  -- p. ej. "L,M,X,J,V"
    sin_huecos_alumnos INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE recesos (
    id INTEGER PRIMARY KEY,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL
);

CREATE TABLE grados (
    id INTEGER PRIMARY KEY,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL,
    UNIQUE (nivel_id, nombre)
);

CREATE TABLE profesores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    carga_max_semanal_min INTEGER NOT NULL,
    carga_max_diaria_min INTEGER NOT NULL,
    max_consecutivas INTEGER NOT NULL
);

CREATE TABLE grupos (
    id INTEGER PRIMARY KEY,
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    seccion TEXT NOT NULL,
    estudiantes INTEGER NOT NULL DEFAULT 0,
    titular_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL,
    UNIQUE (grado_id, seccion)
);

CREATE TABLE asignaturas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    espacio_requerido TEXT,
    max_horas_dia INTEGER NOT NULL,
    bloque_doble TEXT NOT NULL CHECK (bloque_doble IN ('no', 'preferido', 'obligatorio')),
    exigente INTEGER NOT NULL DEFAULT 0,
    color TEXT NOT NULL
);

CREATE TABLE plan_estudios (
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    horas_semanales INTEGER NOT NULL,
    PRIMARY KEY (grado_id, asignatura_id)
);

CREATE TABLE profesor_asignatura (
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    PRIMARY KEY (profesor_id, asignatura_id)
);

CREATE TABLE profesor_grado (
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    grado_id INTEGER NOT NULL REFERENCES grados(id) ON DELETE CASCADE,
    PRIMARY KEY (profesor_id, grado_id)
);

CREATE TABLE disponibilidad (
    id INTEGER PRIMARY KEY,
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    dia TEXT NOT NULL,
    inicio INTEGER NOT NULL,
    fin INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('disponible', 'preferible_no'))
);

CREATE TABLE espacios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL,
    cantidad INTEGER NOT NULL
);

CREATE TABLE asignaciones_fijas (
    id INTEGER PRIMARY KEY,
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    profesor_id INTEGER REFERENCES profesores(id) ON DELETE SET NULL,
    dia TEXT NOT NULL,
    indice_franja INTEGER NOT NULL
);

CREATE TABLE soluciones (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL,
    tiempo_s REAL NOT NULL,
    penalizaciones TEXT NOT NULL,  -- JSON
    nota TEXT NOT NULL DEFAULT ''
);

CREATE TABLE asignaciones (
    id INTEGER PRIMARY KEY,
    solucion_id INTEGER NOT NULL REFERENCES soluciones(id) ON DELETE CASCADE,
    grupo_id INTEGER NOT NULL REFERENCES grupos(id) ON DELETE CASCADE,
    asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id) ON DELETE CASCADE,
    profesor_id INTEGER NOT NULL REFERENCES profesores(id) ON DELETE CASCADE,
    nivel_id INTEGER NOT NULL REFERENCES niveles(id) ON DELETE CASCADE,
    dia TEXT NOT NULL,
    indice INTEGER NOT NULL
);

CREATE INDEX idx_asignaciones_solucion ON asignaciones(solucion_id);
CREATE INDEX idx_disponibilidad_profesor ON disponibilidad(profesor_id);
