"""Extraer el CSV educativo del MEN sin modificar sus valores originales."""

import csv
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


LOGGER = logging.getLogger(__name__)


def extraer_educacion(
    configuracion_fuente: Mapping[str, Any], raiz_proyecto: Path
) -> pd.DataFrame:
    """Leer Bronze y devolver una tabla; la limpieza ocurre en otro modulo.

    Recibe el bloque ``sources.education_stats`` del YAML y la raiz del
    proyecto. Las rutas relativas se resuelven desde esa raiz, no desde la
    carpeta donde el usuario haya abierto la terminal.
    """
    # Esta funcion corresponde exclusivamente a la fuente educativa CSV.
    if configuracion_fuente.get("file_type") != "csv":
        raise ValueError("La fuente educativa debe declarar file_type: csv.")
    ruta = Path(configuracion_fuente["path"])
    if not ruta.is_absolute():
        ruta = Path(raiz_proyecto) / ruta
    ruta = ruta.resolve()
    if not ruta.is_file():
        raise FileNotFoundError("No existe el archivo educativo: {}".format(ruta))

    # Copiar las opciones evita alterar la configuracion recibida.
    opciones = dict(configuracion_fuente["read_options"])
    if opciones.get("dtype") != "string":
        raise ValueError("Educacion debe leerse como string para conservar los codigos.")
    if opciones.get("keep_default_na") is not False:
        raise ValueError("Declare keep_default_na: false y los vacios explicitamente.")
    if "chunksize" in opciones:
        raise ValueError("El extractor educativo devuelve una tabla, no bloques.")

    # Revisar el encabezado original antes de pandas: pandas puede renombrar
    # encabezados repetidos, lo que ocultaria un problema de estructura.
    with ruta.open("r", encoding=opciones["encoding"], newline="") as archivo:
        encabezados = next(csv.reader(archivo, delimiter=opciones["sep"]), [])
    repetidos = [nombre for nombre, cantidad in Counter(encabezados).items() if cantidad > 1]
    if repetidos:
        raise ValueError("El CSV repite encabezados: {}".format(repetidos))
    faltantes = sorted(set(configuracion_fuente["required_columns"]) - set(encabezados))
    if faltantes:
        raise ValueError("Faltan columnas educativas obligatorias: {}".format(faltantes))

    # Aqui solo leemos: no rellenamos faltantes, filtramos filas ni escribimos
    # sobre Bronze. El resultado conserva todas las columnas de la fuente.
    LOGGER.info("Leyendo la fuente educativa: %s", ruta.name)
    datos = pd.read_csv(ruta, **opciones)
    if datos.empty:
        raise ValueError("El archivo educativo no contiene registros.")
    LOGGER.info("Extraidas %s filas y %s columnas", len(datos), len(datos.columns))
    return datos
