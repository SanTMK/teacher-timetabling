# Decisiones de diseño

Creado con Claude. Registro de las decisiones que la especificación no cubre o deja abiertas.

## Generales

- **Python 3.13 y `uv`.** El proyecto ya venía configurado con `uv` y `.python-version = 3.13`
  (la especificación pide ≥ 3.11). Se conserva.
- **Punto de entrada.** `timetabling = "timetabling.cli:main"`. Sin subcomando abre la GUI
  (mientras la GUI no exista, avisa y termina con código 1).
- **Pydantic v2 para todo el dominio**, con `validate_assignment=True` para que las ediciones
  posteriores también se validen.

## Dominio

- **Nombre del grupo** = nombre del grado + sección (`"7°" + "A"` → `7°A`).
- **Nivel preescolar (B7)** se identifica por el nombre del nivel: `"Preescolar"` (sin
  distinguir mayúsculas). Es la opción más simple y no requiere un campo extra.
- **Recesos y disponibilidad** viven dentro de `Nivel` y `Profesor` respectivamente (listas),
  aunque en SQLite tienen tabla propia.
- **Capacidad de un tipo de espacio** = suma de `cantidad` de todos los espacios de ese tipo.
- **`Franja.receso_antes`** registra la separación por receso: es verdadero cuando entre la
  franja y la anterior del mismo día hubo un receso. `separadas_por_receso()` además considera
  separadas dos franjas si hay cualquier hueco de tiempo entre ellas.
- **Id de franja** es la cadena `"nivel:día:índice"`; no se guarda en la base.

## Disponibilidad

- Una franja es válida para un profesor si cabe completa en la **unión** de sus rangos de ese
  día (rangos contiguos o traslapados se fusionan, sin importar el tipo). Es `preferible_no` si
  toca cualquier rango de ese tipo. Así, «disponible 8–10 + preferible no 10–12» permite una
  franja 9:30–10:20 marcada como `preferible_no`.
- El verificador comprueba D5 de forma independiente, minuto a minuto, con la misma regla.

## Persistencia

- **Pesos** de las restricciones blandas se guardan como JSON en `configuracion.pesos`; así
  agregar un peso nuevo no requiere migración (los faltantes toman su valor por defecto).
- **Penalizaciones** de una solución también se guardan como JSON.
- **Borrados:** en cascada para lo que depende estructuralmente (recesos, grados, grupos,
  disponibilidad, plan, relaciones, asignaciones de soluciones). `titular_id` y
  `asignaciones_fijas.profesor_id` usan `SET NULL` para no perder el grupo ni la fijación.
  `Repositorio.afectados_por_eliminar()` cuenta lo afectado para que la GUI advierta.
- `reemplazar_datos()` borra también las soluciones guardadas, porque dejarían de corresponder.
- Guardar una hora semanal en 0 elimina la fila del plan.
- **Migraciones:** `esquema.sql` siempre describe la versión actual (proyectos nuevos);
  `MIGRACIONES[n]` lleva de `n-1` a `n`. Abrir un proyecto de una versión más nueva produce
  `ErrorVersionEsquema`.

## Modelo

- **D3** usa cliques maximales del grafo de traslapes (Bron–Kerbosch con pivote), calculados
  una vez y restringidos a las franjas de cada profesor; se descartan duplicados. Las franjas
  aisladas forman cliques de un elemento, lo que cubre «una clase por franja» dentro del mismo
  nivel.
- **D6** se formula como `Σ_s x[g,a,p,s] = horas · y[g,a,p]` (más fuerte que `x ≤ y` y lo
  implica) junto con `Σ_p y[g,a,p] = 1`.
- **D7 diaria** solo se agrega cuando la suma de franjas posibles del día supera el tope.
- **Claves de suposición:** D3 → `profesor`, D7 → `carga`, D8 → `consecutivas`, D9 →
  `espacio`, D10 → `diaria`, D11 → `bloque`, D12 → `sin_huecos`, D13 → `fija`.
- **Variables auxiliares** `z[g,a,s]` (el grupo recibe la asignatura en la franja) y
  `o[p,s]` (el profesor da clase en la franja), iguales a sumas de `x`. En modo diagnóstico
  son enteras para no imponer D2/D3 fuera de sus suposiciones.
- **D8** considera «consecutivas» las franjas contiguas del mismo nivel y día **sin receso
  intermedio**: un receso reinicia la cuenta. **Limitación conocida:** no cubre secuencias
  que cruzan niveles (un profesor que encadena una clase de primaria con una de secundaria
  no las acumula).
- **D9** usa los mismos cliques de traslape (con margen de traslado entre niveles), lo que es
  algo más estricto que la ocupación física. El verificador comprueba la ocupación física
  real (clases cuyo horario coincide), que el modelo siempre cumple.
- **D10** con `max_horas_dia = 2` prohíbe los pares de franjas no adyacentes del mismo día
  (una franja separada por receso no es adyacente).
- **D11** usa variables de par `b` sobre franjas adyacentes y de hora suelta `u`, con
  `z[s] = Σ b(pares con s) + u[s]`; en `obligatorio`, `Σ u ≤ horas % 2`. La misma estructura
  alimenta B8 en `preferido`.
- **D12** se formula sobre la ocupación total del grupo: `ocupada[k] ≥ ocupada[k+1]`.
- **D13** con una franja o profesor imposible (sin variable) hace el modelo infactible; la
  validación global lo reporta antes.
- Cada restricción se registra bajo una *clave* (`curricular`, `grupo`, `profesor`, `fija`…)
  que el diagnóstico de infactibilidad usará como literal de suposición.

## Validación

- **Espacios (validación 5)** se compara por nivel: clases del nivel que requieren el tipo ≤
  franjas del nivel × cantidad.
- **Capacidad docente (validación 3)**: la oferta de cada profesor habilitado es
  `min(carga máxima semanal, minutos de franjas del nivel en que está disponible)`. Es una
  condición necesaria, no suficiente (un profesor puede contarse en varias asignaturas).
- Se agregó un error extra: asignatura con bloque doble obligatorio y `max_horas_dia < 2`.

## Resolución

- Si se cancela antes de que el solver arranque, el resultado es `CANCELADO` sin asignaciones.
  Si se cancela con una solución hallada, el estado es `CANCELADO` y se conservan las
  asignaciones (y pueden guardarse tras verificarse).
- El tiempo de construcción del modelo se descuenta del tiempo límite (mínimo 1 s de búsqueda).
- **Resolución en dos etapas.** Con el objetivo activo, el tiempo hasta la primera solución
  del ejemplo mediano resultó muy variable (de 7 s a más de 60 s entre corridas idénticas con
  8 hilos), mientras que el modelo sin objetivo se resuelve en ~5 s de forma estable. Por eso
  `Resolutor` primero busca una solución factible sin objetivo (`stop_after_first_solution`)
  y luego restaura el objetivo y optimiza el tiempo restante usando esa solución como pista
  (`add_hint` sobre las `x`). Si la segunda etapa no encuentra nada a tiempo (o se cancela
  antes), se devuelve la solución de la primera; en ese caso los valores de penalización
  informados son cotas superiores. El progreso de la primera etapa llega con
  `mejor_objetivo = None`.

## Ejemplos

- Pequeño: 5 grupos (K3A, 1°A, 2°A, 7°A, 7°B), 12 profesores.
- Mediano: 30 grupos (6 de preescolar, 12 de primaria, 12 de secundaria), 42 profesores.
- Preescolar 45 min, primaria y secundaria 50 min, con horarios de inicio y recesos distintos
  y margen de traslado de 10 min, para ejercitar los traslapes entre niveles.

## Restricciones blandas

- Las penalizaciones con peso 0 no se construyen (el modelo queda más chico).
- **B1** se calcula por profesor, nivel y día con variables «ya empezó» / «aún no termina»;
  los huecos entre clases de niveles distintos no se cuentan (igual que D8).
- **B2** cuenta, por día, las clases más allá de la primera (`max(0, Σ − 1)`), solo si las
  horas semanales son ≥ 2 y ≤ días lectivos.
- **B3** «después de la mitad de la jornada»: la franja empieza en o después del punto medio
  entre `inicio_jornada` y `fin_jornada` del nivel.
- **B5** suma los días con al menos una clase de cada profesor.
- **B6** compara solo profesores que dan la misma asignatura **en el mismo nivel** (los de
  otros niveles no pueden repartirse esos grupos) y usa su carga total. Se mide en unidades de
  la hora-clase más corta, redondeando hacia arriba.
- **B7** aplica a grupos con titular de un nivel llamado «Preescolar».
- **B8** cuenta las horas sueltas menos la hora impar inevitable (`Σ u − horas % 2`).

## Diagnóstico de infactibilidad

- Según la documentación de `cp_model.proto` (campo
  `sufficient_assumptions_for_infeasibility`): solo se llena si el estado es `INFEASIBLE`;
  **solo se minimiza con un único hilo y si el problema no es de optimización** (si no,
  devuelve todas las suposiciones); y no garantiza un subconjunto irreducible.
- Por eso el diagnóstico reconstruye el modelo **sin objetivo**, con `num_workers = 1`, y luego
  aplica un **filtro de eliminación** (quita cada suposición y comprueba si sigue siendo
  infactible, con un máximo de 10 s por intento y 60 s en total).
- Las igualdades estructurales (definición de `z`, `o` y de los pares de bloque doble) no se
  condicionan a suposiciones; si el núcleo queda vacío, se informa un conflicto estructural.

## Interfaz gráfica (Fase 4)

- **Pantallas de lista + formulario** (Niveles, Asignaturas, Profesores, Espacios): lista a la
  izquierda y formulario a la derecha, en vez de tablas editables en línea. Es más simple y
  permite mostrar cada error junto a su campo. El Plan de estudios sí es una matriz editable.
- Los cambios se guardan al pulsar **Guardar** en cada formulario (el Plan se guarda al
  editar cada celda). Al cambiar de pantalla se vuelven a leer los datos; las ediciones sin
  guardar de la pantalla que se deja se descartan.
- Los errores de pydantic se traducen al español (`traducir_error`). El rango de la jornada
  se valida en el campo `fin_jornada` para que el error aparezca junto a ese campo aun cuando
  haya otros errores en el formulario.
- **Editor de disponibilidad:** intervalos de 15 min entre la hora más temprana y la más
  tardía de todos los niveles (y de los rangos ya cargados). Un rango no alineado a 15 min se
  **redondea hacia adentro** al cargarse (solo se marcan los intervalos completamente
  cubiertos), de modo que nunca se amplía la disponibilidad. Los ejemplos usan horas
  alineadas. El arrastre marca un rectángulo días × horas; «copiar día» usa el último día
  pulsado (en negrita).
- Las franjas de referencia se dibujan como **bandas tenues por nivel** en el borde izquierdo
  de cada día (un segmento por franja), con leyenda debajo; los contornos sobre toda la celda
  saturaban la cuadrícula cuando el profesor atiende varios niveles.
- **Proyectos recientes** se guardan con `QSettings` (local).
- **Guardar como** copia el archivo y continúa trabajando sobre la copia.
- Los problemas de validación de **asignaciones fijas** llevan, por ahora, a Grados y grupos;
  la edición de fijas llega con la pantalla de Resultados (Fase 5).
- `colores.py` (contraste de texto) vive en `dominio/` porque lo usarán la interfaz y la
  exportación, y la exportación no puede depender de la interfaz.

## Resultados y exportación (Fase 5)

- **Cuadrícula común** (`dominio/cuadricula.py`): la vista de horario de la interfaz y la
  exportación a Excel usan la misma disposición (filas de franjas con recesos intercalados, o
  filas de 5 min para profesores multinivel). Vive en `dominio/` y recibe las franjas ya
  generadas, para que `exportacion/` solo dependa del dominio, como pide la arquitectura.
  `dominio/estadisticas.py` (carga docente, penalización total) sigue el mismo criterio.
- **Hoja de espacio:** una por tipo de espacio **y nivel** (las franjas difieren entre
  niveles); cada celda lista los grupos que usan ese tipo en la franja.
- **Hojas de profesor:** solo para profesores con al menos una clase en la solución.
- **Leyenda** se incluye siempre; «Resumen» controla también la hoja CargaDocente.
- **Impresión:** horizontal, carta, ajuste a 1×1 página, márgenes de 0,25", encabezado con
  escuela y título de la hoja, pie con fecha de generación y «Página &P de &N». Las hojas de
  horario ocultan la cuadrícula de pantalla (la estructura la dan los bordes); en la escala
  proporcional solo se marca cada media hora con una línea tenue. XlsxWriter omite
  `fitToWidth/fitToHeight = 1` porque es el valor por defecto de OOXML.
- **Nombres de hoja:** se reemplazan `[]:*?/\` por `_`, se recortan a 31 caracteres y los
  duplicados (sin distinguir mayúsculas) reciben « (2)», « (3)»…
- **Penalización total** mostrada = Σ peso × valor de cada penalización, con los pesos
  actuales de la configuración.
- **Trabajador:** `QThread` con una copia de los datos; la solución se guarda en el hilo de la
  interfaz (la conexión SQLite no se comparte entre hilos). Tras resolver verifica; si es
  infactible, diagnostica con un límite de 30 s (este paso no se puede cancelar).
- **Bloqueo durante la resolución:** se deshabilitan todas las pantallas salvo Generar y las
  acciones Nuevo/Abrir/Guardar como; se puede navegar pero no editar. Cerrar la ventana
  cancela la búsqueda y espera a que termine el hilo.
- **Fijar/desfijar:** clic derecho sobre una clase en las vistas por grupo o por profesor.
  Fijar crea una `AsignacionFija` con grupo, asignatura, profesor, día e índice de franja;
  desfijar borra las fijas de ese grupo, asignatura, día y franja. La solución mostrada no
  cambia: las fijas se aplican en la próxima generación. En la vista por espacio no se fija.

## Empaquetado (Fase 6)

- **PyInstaller en modo carpeta** (`onedir`), no `onefile`: arranca más rápido (no
  descomprime ~200 MB en cada inicio) y es más fiable con las bibliotecas nativas de Qt y
  OR-Tools. En macOS se produce un `.app`; en Windows una carpeta con `Timetabling.exe`.
  Se distribuye como `.zip`.
- **OR-Tools no trae hook** de PyInstaller: el `.spec` usa `collect_all("ortools")`.
- `esquema.sql` y el ícono se incluyen como datos del paquete (se leen con
  `importlib.resources`).
- **Ventana sin consola** (`console=False`). El mismo ejecutable acepta los subcomandos de la
  CLI cuando se lanza desde una terminal (en macOS:
  `Timetabling.app/Contents/MacOS/Timetabling generar …`); en Windows la salida de texto no se
  ve porque no hay consola.
- **Ícono** dibujado con Qt por `empaquetado/generar_icono.py` (calendario con celdas de
  colores); genera `.icns` con `iconutil` en macOS y `.ico` para Windows.
- **Sin firma de código:** PyInstaller firma el `.app` *ad hoc*; macOS pide «clic derecho →
  Abrir» la primera vez y Windows muestra SmartScreen. El README lo explica.
- **Verificación hecha (macOS arm64):** sin variables de entorno ni Python en el `PATH`
  (`env -i`), el ejecutable crea el ejemplo, resuelve, verifica y exporta a Excel; con la red
  bloqueada por `sandbox-exec (deny network*)` resuelve igual y la interfaz arranca. El
  ejecutable no enlaza con ningún Python externo (`otool -L`). **No verificado:** una máquina
  distinta, Windows y macOS Intel (hay que construir en cada plataforma).
