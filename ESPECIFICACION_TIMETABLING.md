# Especificación: Programa de Timetabling Escolar

> Documento creado con Claude. Especificación para implementar con Claude Code.

## 0. Instrucciones para Claude Code

- Implementa el proyecto por fases (sección 15). Al terminar cada fase, ejecuta las pruebas y verifica sus criterios de aceptación antes de seguir.
- **Cada archivo `.py` y el `README.md` deben comenzar indicando que fueron creados con Claude.** En Python, como primera línea del docstring del módulo; en el README, como primera línea bajo el título.
- Si una decisión no está cubierta aquí, elige la opción más simple y regístrala en `DECISIONES.md`.
- Idioma: identificadores del dominio, docstrings, textos de la interfaz y mensajes al usuario en **español**.

---

## 1. Objetivo

Aplicación de escritorio en Python que genera el horario semanal de una escuela con preescolar, primaria y secundaria, asignando un profesor a cada hora-clase de cada grupo. Los horarios no están preestablecidos: el programa decide en qué franja va cada clase, respetando las horas-clase semanales exigidas por el plan de estudios.

Los datos se capturan y se guardan **dentro de la propia aplicación**. Excel se usa **únicamente como formato opcional de exportación** de los horarios finales.

## 2. Requisitos no funcionales

- **100 % local y sin conexión.** Ninguna llamada de red, ningún servidor (tampoco en `localhost`), ninguna telemetría.
- **Interfaz gráfica de escritorio** para capturar datos, generar y consultar horarios.
- **Cada escuela es un archivo de proyecto** (base de datos SQLite) que se puede abrir, guardar, copiar como respaldo y mover entre computadoras.
- **Exportación opcional a Excel** de los horarios, estilizada y lista para imprimir.
- **Empaquetable** con PyInstaller como ejecutable para usuarios sin Python instalado.
- Python 3.11 o superior, con anotaciones de tipo en todo el código.
- Rendimiento objetivo: escuela de ~30 grupos y ~40 profesores resuelta en menos de 5 minutos en una laptop común. La interfaz nunca se congela durante la resolución.

## 3. Stack

| Paquete | Uso |
|---|---|
| `PySide6` | Interfaz gráfica de escritorio |
| `sqlite3` (biblioteca estándar) | Persistencia del proyecto |
| `ortools` | Solver CP-SAT |
| `pydantic` (v2) | Validación de datos del dominio |
| `XlsxWriter` | Exportación a Excel |
| `typer` | Línea de comandos auxiliar (desarrollo y pruebas) |
| `pytest`, `pytest-qt`, `ruff` | Pruebas y estilo |
| `openpyxl` | Solo en pruebas, para leer y verificar el Excel exportado |
| `PyInstaller` | Empaquetado |

## 4. Arquitectura

Regla principal: **el núcleo no conoce la base de datos, la interfaz ni Excel**; trabaja solo con objetos del dominio. Dependencias permitidas:

```
interfaz (gui, cli) → persistencia, nucleo, exportacion → dominio
```

```
timetabling/
├── README.md
├── DECISIONES.md
├── pyproject.toml
├── src/timetabling/
│   ├── dominio/
│   │   └── modelos.py            # dataclasses / modelos pydantic
│   ├── persistencia/
│   │   ├── esquema.sql
│   │   ├── migraciones.py        # versionado del esquema
│   │   └── repositorio.py        # SQLite ↔ objetos del dominio
│   ├── nucleo/
│   │   ├── franjas.py            # franjas por nivel + matriz de traslapes
│   │   ├── validacion.py         # revisiones previas
│   │   ├── modelo.py             # variables y restricciones duras
│   │   ├── objetivo.py           # restricciones blandas
│   │   ├── resolver.py           # ejecución del solver (cancelable)
│   │   ├── diagnostico.py        # explicación de infactibilidad
│   │   └── verificador.py        # revisión independiente
│   ├── exportacion/
│   │   ├── estilos.py
│   │   └── excel.py
│   ├── gui/
│   │   ├── app.py                # ventana principal
│   │   ├── pantallas/            # una pantalla por sección (sección 12)
│   │   ├── widgets/              # editor de disponibilidad, vista de horario, etc.
│   │   └── trabajador.py         # QThread para el solver
│   ├── ejemplo.py                # genera proyectos de ejemplo
│   └── cli.py
└── pruebas/
```

## 5. Modelo del dominio

Las horas se representan internamente como **minutos desde medianoche** (`int`). Los días son `L, M, X, J, V` (configurable por nivel).

| Entidad | Campos |
|---|---|
| `Configuracion` | nombre_escuela, margen_traslado_min, tiempo_limite_s, hilos, pesos de restricciones blandas |
| `Nivel` | id, nombre, duracion_min, inicio_jornada, fin_jornada, dias, recesos, sin_huecos_alumnos (bool) |
| `Receso` | nivel_id, nombre, inicio, fin |
| `Grado` | id, nivel_id, nombre |
| `Grupo` | id, grado_id, seccion, estudiantes, titular_id (opcional) |
| `Asignatura` | id, nombre, espacio_requerido (tipo o None), max_horas_dia, bloque_doble (`no`/`preferido`/`obligatorio`), exigente (bool), color (hex) |
| `PlanEstudios` | grado_id, asignatura_id, horas_semanales (en horas-clase del nivel) |
| `Profesor` | id, nombre, asignaturas, grados, disponibilidad, carga_max_semanal_min, carga_max_diaria_min, max_consecutivas |
| `Disponibilidad` | profesor_id, dia, inicio, fin, tipo (`disponible`/`preferible_no`) |
| `Espacio` | id, nombre, tipo, cantidad |
| `AsignacionFija` | grupo_id, asignatura_id, profesor_id (opcional), dia, indice_franja |
| `Franja` (generada, no se guarda) | id, nivel_id, dia, indice, inicio, fin |
| `Solucion` | id, fecha, estado, tiempo_s, penalizaciones, nota |
| `Asignacion` | solucion_id, grupo_id, asignatura_id, profesor_id, franja (nivel, día, índice) |

La carga de los profesores se mide en **minutos**, no en horas-clase, porque la duración varía por nivel.

## 6. Persistencia (`persistencia/`)

- Un proyecto es un único archivo SQLite con extensión `.horario`.
- Tablas que reflejan las entidades del dominio, más tablas de relación `profesor_asignatura` y `profesor_grado`, `soluciones` y `asignaciones`.
- `PRAGMA foreign_keys = ON`; borrados en cascada donde tenga sentido (por ejemplo, borrar un profesor borra su disponibilidad). Antes de borrar algo referenciado por otras entidades, la interfaz debe advertir qué se verá afectado.
- Tabla `esquema_version` y módulo `migraciones.py` para actualizar proyectos creados con versiones anteriores del programa.
- `repositorio.py` es la única puerta de acceso a la base de datos: carga un `DatosEscuela` completo para el núcleo y ofrece operaciones de alta, baja y modificación para la interfaz.
- Las soluciones generadas se **guardan en el proyecto**, para poder consultarlas, compararlas y exportarlas después sin volver a resolver.

## 7. Generación de franjas y traslapes (`franjas.py`)

1. Para cada nivel y día, generar franjas consecutivas de `duracion_min` desde `inicio_jornada`. Si una franja chocaría con un receso, la siguiente comienza al terminar el receso. Detenerse cuando la franja no quepa antes de `fin_jornada`.
2. Registrar si entre dos franjas consecutivas hay un receso (`separadas_por_receso`), necesario para bloques dobles.
3. **Matriz de traslapes:** dos franjas `[a, b)` y `[c, d)` del mismo día se traslapan si `a < d + margen` y `c < b + margen`, donde `margen` es `margen_traslado_min` (aplica solo entre niveles distintos). Guardar como diccionario `franja_id → set[franja_id]`.
4. Una franja es válida para un profesor si cabe **completa** en un rango de disponibilidad de ese día.

## 8. Restricciones duras (`modelo.py`)

**Variables.** `x[g, a, p, s]` booleana: el profesor `p` da la asignatura `a` al grupo `g` en la franja `s`. Crear **solo** las combinaciones donde `a` está en el plan del grado de `g`, `p` está habilitado para `a` y para el grado de `g`, `s` pertenece al nivel de `g`, y `p` tiene disponibilidad (`disponible` o `preferible_no`) que cubre `s`. Variable auxiliar `y[g, a, p]` booleana: `p` está a cargo de `a` en `g`.

| # | Restricción | Formulación |
|---|---|---|
| D1 | Cumplimiento curricular | `Σ_{p,s} x[g,a,p,s] = horas_semanales(grado(g), a)` |
| D2 | Un maestro por grupo y franja | `Σ_{a,p} x[g,a,p,s] ≤ 1` |
| D3 | Profesor en un solo lugar | Para cada `p` y cada clique de franjas mutuamente traslapadas: `Σ x ≤ 1`. Si construir cliques es costoso, usar pares traslapados |
| D4 | Competencia | Garantizada por la poda de variables |
| D5 | Disponibilidad | Garantizada por la poda de variables |
| D6 | Continuidad docente | `Σ_p y[g,a,p] = 1`; `x[g,a,p,s] ≤ y[g,a,p]` |
| D7 | Carga máxima | Minutos semanales y diarios por profesor ≤ sus topes |
| D8 | Clases consecutivas | En cada ventana de `max_consecutivas + 1` franjas consecutivas del mismo nivel y día, el profesor tiene a lo sumo `max_consecutivas` clases. (Limitación conocida: no cubre secuencias que cruzan niveles; documentarlo en `DECISIONES.md`) |
| D9 | Espacios especiales | Para cada tipo de espacio y cada clique de franjas traslapadas: clases que lo requieren ≤ `cantidad` |
| D10 | Máximo diario por asignatura | Por grupo, asignatura y día: `Σ ≤ max_horas_dia`. Si `max_horas_dia = 2`, las dos deben ser consecutivas: prohibir pares de franjas no adyacentes el mismo día |
| D11 | Bloque doble obligatorio | Las horas de la asignatura se agrupan en pares de franjas adyacentes no separadas por receso (si las horas son impares, una queda suelta) |
| D12 | Sin huecos para alumnos | Si `sin_huecos_alumnos` es verdadero en el nivel: `ocupada[g,d,k] ≥ ocupada[g,d,k+1]`, de modo que las clases del día empiezan en la primera franja y son continuas |
| D13 | Asignaciones fijas | Forzar las asignaciones fijas (si falta `profesor_id`, solo se fija grupo, asignatura y franja) |

Los recesos se respetan por construcción de las franjas.

## 9. Restricciones blandas (`objetivo.py`)

Minimizar la suma ponderada de penalizaciones. Los pesos se editan en la pantalla de Configuración (valores por defecto entre paréntesis).

| # | Penalización | Peso |
|---|---|---|
| B1 | Huecos de profesores: franjas libres entre su primera y última clase del día (por nivel, usando variables de "ya empezó" y "aún no termina") | 10 |
| B2 | Mala distribución semanal: cada clase más allá de una por día de la misma asignatura, cuando las horas semanales ≤ días lectivos | 8 |
| B3 | Asignatura `exigente` después de la mitad de la jornada | 3 |
| B4 | Clase en franja marcada `preferible_no` por el profesor | 6 |
| B5 | Días con clase por profesor (fomenta concentrar a docentes por hora) | 2 |
| B6 | Desequilibrio de carga: diferencia entre la carga máxima y mínima en minutos entre profesores de la misma asignatura (escalada) | 1 |
| B7 | Grupo con `titular_id` en nivel preescolar: franjas no impartidas por el titular | 5 |
| B8 | Asignatura con `bloque_doble = preferido`: horas no emparejadas | 4 |

## 10. Validaciones

**En los formularios:** cada campo se valida al guardar (tipos, rangos, horas de inicio menores que las de fin, nombres no vacíos ni duplicados). Los errores se muestran junto al campo.

**Validación global antes de resolver (`validacion.py`):** cada problema se reporta con entidad, elemento, severidad (`error` o `advertencia`) y mensaje claro en español. Con al menos un `error`, no se ejecuta el solver.

1. Cada (grado, asignatura) del plan tiene al menos un profesor habilitado.
2. Las horas del plan de cada grado caben en las franjas semanales de su nivel.
3. Capacidad docente por asignatura y nivel: minutos demandados ≤ minutos disponibles de los profesores habilitados (considerando su carga máxima). Mensaje ejemplo: "Inglés en secundaria requiere 2.400 min/semana; los profesores habilitados suman 1.800".
4. Cada rango de disponibilidad cubre al menos una franja de algún nivel que el profesor atiende (advertencia si no).
5. Demanda semanal de cada tipo de espacio ≤ franjas × cantidad.
6. Asignaciones fijas coherentes: profesor habilitado y disponible, franja existente, sin choques entre sí.
7. `max_horas_dia × días ≥ horas_semanales` para cada asignatura del plan.
8. Elementos incompletos: grados sin grupos, grupos de grados sin plan de estudios, profesores sin asignaturas o sin disponibilidad (advertencias).

## 11. Resolución, verificación y diagnóstico

**`resolver.py`:** construye el modelo, aplica `tiempo_limite_s` e `hilos`, informa progreso (mejor solución encontrada, tiempo transcurrido) mediante callback, permite **cancelar** (`StopSearch`) conservando la mejor solución hallada, y devuelve estado (`OPTIMO`, `FACTIBLE`, `INFACTIBLE`, `SIN_SOLUCION_EN_TIEMPO`, `CANCELADO`), las asignaciones y el valor de cada penalización blanda.

**`verificador.py`:** implementación **independiente** del modelo (no reutiliza sus estructuras) que recibe los datos y la lista de `Asignacion` y comprueba cada restricción dura D1–D13. Se ejecuta siempre tras resolver; si encuentra violaciones, la solución no se guarda y se informa como error interno.

**`diagnostico.py`:** si el estado es `INFACTIBLE`, reconstruir el modelo agrupando restricciones bajo literales de suposición (por profesor, por grupo y asignatura, por tipo de restricción) y usar `sufficient_assumptions_for_infeasibility` de CP-SAT para identificar un conjunto pequeño en conflicto. Traducirlo a mensajes legibles. Verifica en la documentación de OR-Tools las condiciones de uso de esa función (por ejemplo, número de workers) y documenta lo encontrado en `DECISIONES.md`.

## 12. Interfaz gráfica (`gui/`)

Ventana principal con barra lateral de navegación entre pantallas. Menú Archivo: Nuevo proyecto, Abrir, Guardar como (copia del archivo), Proyectos recientes. Los cambios se guardan en la base de datos al confirmar cada formulario.

| Pantalla | Contenido |
|---|---|
| **Configuración** | Nombre de la escuela, margen de traslado, tiempo límite, hilos, pesos de las restricciones blandas (con botón "restaurar valores por defecto") |
| **Niveles** | Datos del nivel y sus recesos, con **vista previa de las franjas generadas** que se actualiza al editar |
| **Grados y grupos** | Árbol nivel → grado → grupos; alta, edición y baja |
| **Asignaturas** | Tabla editable; selector de color; tipo de espacio requerido |
| **Plan de estudios** | Matriz editable grados × asignaturas con horas semanales; totales por grado comparados con las franjas disponibles del nivel |
| **Profesores** | Lista y formulario: datos generales, casillas de asignaturas y grados habilitados, y **editor de disponibilidad** |
| **Espacios** | Tabla editable de espacios especiales |
| **Validación** | Lista de problemas de la validación global; doble clic lleva a la pantalla y elemento correspondiente |
| **Generar** | Botón generar, barra de progreso, mejor penalización actual, tiempo transcurrido, botón cancelar; si es infactible, muestra el diagnóstico |
| **Resultados** | Selector de solución guardada; vistas de horario por grupo, por profesor y por espacio; resumen de penalizaciones; carga docente; botón **Exportar a Excel** |

**Editor de disponibilidad:** cuadrícula semanal (días × intervalos de 15 minutos desde la hora más temprana hasta la más tardía de todos los niveles). El usuario arrastra para marcar rangos como `disponible` o `preferible_no` (dos colores) y puede borrar. Superpone en tono tenue las franjas de los niveles que el profesor atiende, como referencia. Incluye "copiar día a toda la semana".

**Vista de horario:** misma lógica visual que la exportación (sección 13): color por asignatura, recesos en gris, y para profesores multinivel una escala de tiempo proporcional.

**Ajustes manuales:** en la vista de horario, menú contextual sobre una clase para **fijarla** (crea una `AsignacionFija`) o desfijarla. Las clases fijas se marcan con un ícono. Al generar de nuevo, se respetan.

**Concurrencia:** el solver corre en un `QThread` (`trabajador.py`) que emite señales de progreso; la interfaz se mantiene receptiva y la edición de datos se bloquea mientras se resuelve.

## 13. Exportación a Excel (`exportacion/`)

Opcional, desde la pantalla de Resultados (y desde la CLI). Usa XlsxWriter. El usuario elige qué incluir: grupos, profesores, espacios, resumen.

| Hoja | Contenido |
|---|---|
| `Resumen` | Escuela, fecha de generación, estado del solver, tiempo de cómputo, valor de cada penalización, restricciones blandas incumplidas |
| Una por grupo (`7A`, `7B`…) | Filas = franjas de su nivel (con hora), columnas = días. Celda: asignatura y profesor |
| Una por profesor | Celda: asignatura y grupo. Ver formato abajo |
| Una por tipo de espacio especial | Ocupación por franja |
| `CargaDocente` | Profesor, minutos asignados, máximo, porcentaje, días con clase, huecos |
| `Leyenda` | Asignatura y su color |

**Hoja de profesor:** si trabaja en un solo nivel, usar la cuadrícula de ese nivel. Si trabaja en varios, usar filas de 5 minutos con altura reducida y representar cada clase como una celda combinada que abarque su duración real.

**Estilo e impresión:**

- Color por asignatura con texto en contraste suficiente.
- Recesos como filas grises combinadas con su nombre.
- Encabezados en negrita con fondo, bordes finos, texto ajustado y centrado.
- Orientación horizontal, tamaño carta, ajuste a una página, márgenes estrechos.
- Encabezado de impresión: nombre de la escuela y de la hoja. Pie: fecha de generación y número de página.
- Nombres de hoja válidos para Excel (máximo 31 caracteres, sin caracteres prohibidos, únicos).

## 14. Línea de comandos auxiliar (`cli.py`)

Pensada para desarrollo, pruebas y usuarios técnicos; no es la vía principal de uso.

```
timetabling ejemplo  proyecto.horario [--tamano pequeno|mediano]
timetabling validar  proyecto.horario
timetabling generar  proyecto.horario [--tiempo-limite 300] [--hilos 8] [--exportar horario.xlsx]
timetabling exportar proyecto.horario --solucion ID --salida horario.xlsx
```

Y `timetabling` sin argumentos (o el ejecutable empaquetado) abre la interfaz gráfica.

## 15. Fases y criterios de aceptación

**Fase 1 — Base.** Dominio, esquema SQLite, repositorio, migraciones, franjas y traslapes, generador de proyectos de ejemplo.
*Acepta si:* el ejemplo se crea y se carga de vuelta idéntico; las pruebas de franjas cubren recesos y traslapes entre niveles.

**Fase 2 — MVP de resolución (sin interfaz gráfica).** Restricciones D1–D7 y D13, resolver, verificador, guardado de soluciones, CLI `ejemplo`/`validar`/`generar`.
*Acepta si:* el ejemplo pequeño se resuelve desde la CLI y el verificador no reporta violaciones.

**Fase 3 — Robustez y calidad del modelo.** Validación global, diagnóstico de infactibilidad, D8–D12, B1–B8.
*Acepta si:* datos defectuosos producen mensajes claros, un caso infactible construido a propósito se diagnostica, y el ejemplo mediano se resuelve en menos de 5 minutos.

**Fase 4 — Interfaz de captura.** Ventana principal, manejo de proyectos, pantallas de Configuración a Espacios, editor de disponibilidad, pantalla de Validación.
*Acepta si:* se puede crear desde cero un proyecto pequeño solo con la interfaz y resolverlo desde la CLI.

**Fase 5 — Interfaz de resultados y exportación.** Pantallas Generar y Resultados, ejecución en hilo con cancelación, ajustes manuales (fijar/desfijar), exportación a Excel.
*Acepta si:* el ciclo completo capturar → generar → fijar → regenerar → exportar funciona sin congelar la interfaz, y el Excel se imprime correctamente.

**Fase 6 — Distribución.** Empaquetado con PyInstaller, ícono, README con instrucciones para usuarios no técnicos.
*Acepta si:* el ejecutable funciona en una máquina sin Python y sin conexión a internet.

## 16. Pruebas

- Unitarias: franjas, traslapes, repositorio (ida y vuelta de todas las entidades), migraciones, cada validación.
- Verificador: soluciones construidas a mano que violan cada restricción dura, una por una.
- Integración: proyectos de ejemplo pequeño y mediano de punta a punta.
- Caso infactible conocido para el diagnóstico.
- Exportación: abrir el `.xlsx` con openpyxl y comprobar hojas, celdas combinadas y configuración de impresión.
- Interfaz (`pytest-qt`): crear un proyecto, agregar entidades, marcar disponibilidad y lanzar la generación.
- Una prueba que confirme que el paquete no importa módulos de red (`requests`, `urllib.request`, `http.client`, `socket`) fuera de dependencias de terceros.
