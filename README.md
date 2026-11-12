# Timetabling escolar

Creado con Claude.

Programa de escritorio que arma el **horario semanal** de una escuela con preescolar,
primaria y secundaria. Usted captura los niveles, grupos, asignaturas, plan de estudios y
profesores; el programa decide en qué hora va cada clase y qué profesor la imparte,
respetando la disponibilidad de los docentes, los recesos y los salones especiales.

- Funciona **sin internet**: nada sale de su computadora.
- Cada escuela se guarda en **un solo archivo** con extensión `.horario`, que puede copiar
  como respaldo o llevar a otra computadora.
- Los horarios se pueden **exportar a Excel**, con colores y listos para imprimir.

---

## 1. Instalación

No necesita instalar Python ni ningún otro programa.

### macOS

1. Descomprima `Timetabling-macos-arm64.zip` (doble clic).
2. Arrastre **Timetabling.app** a la carpeta **Aplicaciones**.
3. La primera vez, haga **clic derecho sobre la aplicación → Abrir** y confirme con
   **Abrir**. (macOS lo pide porque la aplicación no viene de la App Store; después basta con
   doble clic.)

### Windows

1. Haga clic derecho sobre `Timetabling-windows-amd64.zip` → **Extraer todo…**.
2. Abra la carpeta `Timetabling` y haga doble clic en **Timetabling.exe**.
3. Si aparece «Windows protegió su PC», elija **Más información → Ejecutar de todas formas**.

> Consejo: cree un acceso directo a `Timetabling.exe` en el escritorio. No mueva el `.exe`
> fuera de su carpeta: necesita los archivos que lo acompañan.

---

## 2. Primeros pasos

Al abrir el programa, use el menú **Archivo → Nuevo proyecto** y elija dónde guardar el
archivo de su escuela. A la izquierda verá las secciones; recórralas en orden:

| Sección | Qué hacer |
|---|---|
| **Configuración** | Nombre de la escuela y cuánto tiempo puede tardar el cálculo. Si los profesores necesitan unos minutos para cambiar de edificio entre niveles, indíquelos en *Margen de traslado*. |
| **Niveles** | Para preescolar, primaria y secundaria: duración de la clase, hora de entrada y salida, días y recesos. Si alguna hora dura distinto (p. ej. la última hora de 40 min), agréguela en *Horas con duración distinta*. Abajo verá cómo quedan las horas de clase. |
| **Grados y grupos** | Seleccione un nivel → *Agregar grado* (p. ej. «1°»); seleccione el grado → *Agregar grupo* (p. ej. «A»). |
| **Asignaturas** | Nombre, color, máximo de horas por día y, si la necesita, el tipo de salón (laboratorio, cómputo, patio…). |
| **Plan de estudios** | Escriba cuántas horas por semana lleva cada asignatura en cada grado. La columna *Total* se pone en rojo si no caben. |
| **Profesores** | Marque qué asignaturas y grados puede dar cada uno, y **pinte su disponibilidad** arrastrando el ratón sobre la cuadrícula (verde: disponible; naranja: preferiría no). *Copiar día a toda la semana* ahorra tiempo. |
| **Espacios** | Salones especiales y cuántos hay de cada tipo. |
| **Clases fijas** | (Opcional) Elija un grupo y **arrastre** asignaturas con su profesor a las horas de la semana. El horario generado respetará esas clases. |
| **Validación** | Revisa que no falte nada. Haga doble clic en un problema para ir directo a corregirlo. |
| **Generar** | Pulse **Generar horario**. Puede seguir mirando el programa mientras calcula; *Cancelar* se queda con el mejor horario encontrado hasta ese momento. |
| **Resultados** | Horarios por grupo, por profesor y por salón; resumen y carga de cada docente; **Exportar a Excel…**. |

Los cambios se guardan al pulsar **Guardar** en cada formulario (en el plan de estudios, al
escribir cada número).

### Ajustar a mano

Antes de generar, en **Clases fijas** elija un grupo y arrastre un profesor de la lista de la
izquierda (o «cualquiera», para que lo elija el programa) a una hora de la semana. Para mover
una clase, arrástrela a otra hora; para quitarla, devuélvala a la lista o pulse **Supr**. Al
elegir un profesor se sombrean las horas en que no está disponible (gris), preferiría no
(naranja) o ya tiene otra clase fija (rojo). Los choques se avisan en rojo debajo.

También puede ajustar después de generar: en **Resultados**, haga **clic derecho** sobre una clase → **Fijar esta clase** (aparece 📌).
Vuelva a **Generar**: el nuevo horario respetará las clases fijas y acomodará lo demás.
Para quitarla, clic derecho → **Desfijar esta clase**.

### Reajustar un horario que ya está en uso

Cuando la escuela ya trabaja con un horario y cambia algo (llega un profesor sustituto,
alguien deja de poder ciertos días, se agrega un grupo…), no hace falta fijar clase por clase:

1. En **Resultados**, elija el horario que se está usando y pulse **Marcar como vigente**
   (aparece «★ VIGENTE» en la lista). Solo hay uno a la vez.
2. Haga los cambios en los datos (por ejemplo, en **Profesores**). Si un profesor se va,
   conviene **editarlo** (cambiar nombre y disponibilidad por los del sustituto) en lugar de
   eliminarlo: al eliminarlo se borran sus clases de los horarios guardados.
3. En **Generar**, pulse **Reajustar horario vigente**. El programa parte del horario
   vigente y cambia **lo menos posible**: primero intenta conservar las horas cambiando solo
   el profesor; mover una clase de hora le cuesta el doble. El peso de esta preferencia es
   *B9* en Configuración (súbalo si quiere todavía menos movimiento).
4. En **Resultados** verá cuántas clases cambiaron y a cuántos profesores afecta. Las clases
   cambiadas aparecen con **↻** en negrita, y la pestaña **Cambios** las lista (antes →
   después). **Exportar a Excel…** incluye una hoja «Cambios» para avisar a los afectados.
5. Si le convence, pulse **Marcar como vigente** sobre la nueva solución.

### Si no se encuentra horario

Si es imposible cumplir todo (por ejemplo, un profesor tiene muy poca disponibilidad para las
horas que debe dar), la pantalla **Generar** muestra las **posibles causas del conflicto**.
Corrija esos datos y vuelva a intentarlo. Si el cálculo se queda sin tiempo, aumente el
*tiempo límite* en Configuración.

### Respaldos

Su escuela entera está en el archivo `.horario`. Para respaldarla, copie ese archivo (o use
**Archivo → Guardar como…**). Para abrirla en otra computadora, copie el archivo y use
**Archivo → Abrir**.

---

## 3. Para desarrolladores

Requiere [uv](https://docs.astral.sh/uv/) y Python 3.13.

```bash
uv sync
uv run timetabling                  # interfaz gráfica
uv run timetabling ejemplo escuela.horario --tamano mediano
uv run timetabling validar escuela.horario
uv run timetabling generar escuela.horario --tiempo-limite 300 --hilos 8 --exportar horario.xlsx
uv run timetabling exportar escuela.horario --solucion 1 --salida horario.xlsx
```

### Pruebas

```bash
uv run pytest                 # todas (incluye el ejemplo mediano, ~2 min)
uv run pytest -m "not lento"  # sin el ejemplo mediano
uv run ruff check src pruebas
```

### Construir el ejecutable

PyInstaller no compila de un sistema a otro: construya en macOS para macOS y en Windows para
Windows.

```bash
uv sync
uv run python empaquetado/construir.py
```

Genera el ícono, ejecuta PyInstaller con `empaquetado/timetabling.spec` y deja en `dist/` la
aplicación (`Timetabling.app` o la carpeta `Timetabling/` con `Timetabling.exe`) y un `.zip`
para distribuir.

### Publicar una versión

Al subir una etiqueta que empiece con `v`, GitHub Actions
([`.github/workflows/release.yml`](.github/workflows/release.yml)) construye en macOS y en
Windows y crea una *release* con los dos `.zip`:

```bash
git tag v1.0.0
git push origin v1.0.0
```

### Estado

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Dominio, SQLite, migraciones, franjas, ejemplos | ✅ |
| 2 | Resolución D1–D7 y D13, verificador, CLI | ✅ |
| 3 | Validación completa, diagnóstico, D8–D12, B1–B8 | ✅ |
| 4 | Interfaz de captura | ✅ |
| 5 | Interfaz de resultados y exportación a Excel | ✅ |
| 6 | Empaquetado con PyInstaller | ✅ (probado en macOS arm64) |

Las decisiones de diseño están en [DECISIONES.md](DECISIONES.md) y la especificación en
[ESPECIFICACION_TIMETABLING.md](ESPECIFICACION_TIMETABLING.md).
