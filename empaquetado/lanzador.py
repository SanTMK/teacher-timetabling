"""Creado con Claude. Punto de entrada del ejecutable empaquetado con PyInstaller.

Sin argumentos abre la interfaz gráfica; con argumentos funciona como la línea de comandos.
"""

import sys

from timetabling.cli import main

if __name__ == "__main__":
    # Versiones antiguas de macOS agregan «-psn_…» al abrir una .app con doble clic.
    sys.argv = [a for a in sys.argv if not a.startswith("-psn_")]
    main()
