"""Creado con Claude. Línea de comandos auxiliar (desarrollo, pruebas y usuarios técnicos).

Sin argumentos abre la interfaz gráfica.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from timetabling.dominio.modelos import NOMBRES_PENALIZACIONES, DatosEscuela, Solucion
from timetabling.ejemplo import Tamano, crear_proyecto_ejemplo
from timetabling.exportacion.excel import exportar_excel
from timetabling.nucleo.franjas import generar_franjas
from timetabling.nucleo.resolver import Progreso, Resolutor, ResultadoResolucion
from timetabling.nucleo.validacion import Severidad, hay_errores, validar
from timetabling.nucleo.verificador import verificar
from timetabling.persistencia.repositorio import Repositorio

app = typer.Typer(
    help="Generador de horarios escolares. Sin comandos abre la interfaz gráfica.",
    no_args_is_help=False,
    add_completion=False,
)

Proyecto = Annotated[Path, typer.Argument(help="Archivo de proyecto .horario")]


@app.callback(invoke_without_command=True)
def principal(contexto: typer.Context) -> None:
    if contexto.invoked_subcommand is None:
        abrir_interfaz()


def abrir_interfaz() -> None:
    try:
        from timetabling.gui.app import ejecutar
    except ImportError:
        typer.echo("La interfaz gráfica aún no está disponible. Use --help para ver los comandos.")
        raise typer.Exit(1) from None
    raise typer.Exit(ejecutar())


@app.command()
def ejemplo(
    proyecto: Proyecto,
    tamano: Annotated[
        Tamano, typer.Option(help="Tamaño de la escuela de ejemplo")
    ] = Tamano.PEQUENO,
    sobrescribir: Annotated[bool, typer.Option(help="Reemplazar el archivo si existe")] = False,
) -> None:
    """Crea un proyecto de ejemplo."""
    try:
        datos = crear_proyecto_ejemplo(proyecto, tamano, sobrescribir=sobrescribir)
    except FileExistsError as error:
        typer.echo(f"{error}. Use --sobrescribir para reemplazarlo.", err=True)
        raise typer.Exit(1) from None
    typer.echo(
        f"Proyecto creado en {proyecto}: {len(datos.niveles)} niveles, {len(datos.grupos)} "
        f"grupos, {len(datos.profesores)} profesores, {len(datos.asignaturas)} asignaturas."
    )


def _cargar(proyecto: Path) -> DatosEscuela:
    try:
        with Repositorio.abrir(proyecto) as repo:
            return repo.cargar_datos()
    except FileNotFoundError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from None


def _imprimir_validacion(datos: DatosEscuela) -> bool:
    """Imprime los problemas; devuelve verdadero si hay errores."""
    problemas = validar(datos)
    for problema in problemas:
        color = typer.colors.RED if problema.severidad == Severidad.ERROR else typer.colors.YELLOW
        typer.secho(str(problema), fg=color)
    errores = sum(p.severidad == Severidad.ERROR for p in problemas)
    typer.echo(f"{errores} error(es), {len(problemas) - errores} advertencia(s).")
    return hay_errores(problemas)


@app.command("validar")
def comando_validar(proyecto: Proyecto) -> None:
    """Revisa los datos del proyecto sin resolver."""
    if _imprimir_validacion(_cargar(proyecto)):
        raise typer.Exit(1)


def _imprimir_resultado(resultado: ResultadoResolucion) -> None:
    typer.echo(f"Estado: {resultado.estado.value}  ·  tiempo: {resultado.tiempo_s:.1f} s")
    if resultado.objetivo is not None:
        typer.echo(f"Penalización total: {resultado.objetivo:g}")
    for clave, valor in resultado.penalizaciones.items():
        typer.echo(f"  {NOMBRES_PENALIZACIONES.get(clave, clave)}: {valor}")


@app.command()
def generar(
    proyecto: Proyecto,
    tiempo_limite: Annotated[int | None, typer.Option(help="Segundos máximos de búsqueda")] = None,
    hilos: Annotated[int | None, typer.Option(help="Hilos del solver")] = None,
    exportar: Annotated[
        Path | None, typer.Option(help="Exportar el horario a este archivo .xlsx")
    ] = None,
) -> None:
    """Valida, resuelve, verifica y guarda una solución en el proyecto."""
    datos = _cargar(proyecto)
    if _imprimir_validacion(datos):
        typer.secho("Hay errores en los datos; no se ejecuta el solver.", fg=typer.colors.RED)
        raise typer.Exit(1)

    def progreso(p: Progreso) -> None:
        if p.mejor_objetivo is None:
            typer.echo(f"  [{p.tiempo_s:6.1f} s] primera solución válida; optimizando…")
        else:
            typer.echo(f"  [{p.tiempo_s:6.1f} s] solución #{p.soluciones}: {p.mejor_objetivo:g}")

    resolutor = Resolutor(datos, tiempo_limite, hilos, progreso)
    typer.echo("Resolviendo… (Ctrl+C para detener y conservar la mejor solución)")
    try:
        resultado = resolutor.resolver()
    except KeyboardInterrupt:
        resolutor.cancelar()
        raise
    _imprimir_resultado(resultado)

    if not resultado.asignaciones:
        if resultado.estado.value == "INFACTIBLE":
            _imprimir_diagnostico(datos)
        raise typer.Exit(2)

    violaciones = verificar(datos, resultado.asignaciones)
    if violaciones:
        typer.secho("Error interno: la solución viola restricciones duras:", fg=typer.colors.RED)
        for violacion in violaciones[:20]:
            typer.echo(f"  {violacion}")
        raise typer.Exit(3)

    with Repositorio.abrir(proyecto) as repo:
        guardada = repo.guardar_solucion(
            Solucion(
                estado=resultado.estado,
                tiempo_s=round(resultado.tiempo_s, 2),
                penalizaciones=resultado.penalizaciones,
                asignaciones=resultado.asignaciones,
            )
        )
    typer.secho(f"Solución verificada y guardada con id {guardada.id}.", fg=typer.colors.GREEN)
    if exportar is not None:
        _exportar(proyecto, guardada.id, exportar)


def _imprimir_diagnostico(datos: DatosEscuela) -> None:
    try:
        from timetabling.nucleo.diagnostico import diagnosticar
    except ImportError:
        typer.echo("El problema no tiene solución con los datos actuales.")
        return
    typer.secho("Posibles causas del conflicto:", fg=typer.colors.YELLOW)
    for mensaje in diagnosticar(datos):
        typer.echo(f"  • {mensaje}")


def _exportar(proyecto: Path, solucion_id: int, salida: Path) -> None:
    with Repositorio.abrir(proyecto) as repo:
        datos = repo.cargar_datos()
        try:
            solucion = repo.cargar_solucion(solucion_id)
        except KeyError:
            disponibles = ", ".join(str(s.id) for s in repo.listar_soluciones()) or "ninguna"
            typer.echo(
                f"No existe la solución {solucion_id}. Soluciones guardadas: {disponibles}",
                err=True,
            )
            raise typer.Exit(1) from None
    exportar_excel(datos, solucion, generar_franjas(datos), salida)
    typer.echo(f"Horario exportado a {salida}")


@app.command("exportar")
def comando_exportar(
    proyecto: Proyecto,
    solucion: Annotated[int, typer.Option(help="Id de la solución guardada")],
    salida: Annotated[Path, typer.Option(help="Archivo .xlsx de salida")],
) -> None:
    """Exporta una solución guardada a Excel."""
    _exportar(proyecto, solucion, salida)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
