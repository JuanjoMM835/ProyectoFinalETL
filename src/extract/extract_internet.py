"""Leer internet fijo por bloques sin modificar el CSV Bronze."""

import csv
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Generator, Mapping

import pandas as pd


LOGGER = logging.getLogger(__name__)


def extraer_internet(
    configuracion_fuente: Mapping[str, Any], raiz_proyecto: Path
) -> Generator[pd.DataFrame, None, None]:
    """Validar la entrada y devolver un generador de bloques de texto.

    Un generador entrega una tabla cada vez que se itera. Asi no cargamos
    los millones de filas de internet en un unico DataFrame.
    """
    if configuracion_fuente.get("file_type") != "csv":
        raise ValueError("Internet debe declarar file_type: csv.")
    ruta = Path(configuracion_fuente["path"])
    if not ruta.is_absolute():
        ruta = Path(raiz_proyecto) / ruta
    ruta = ruta.resolve()
    if not ruta.is_file():
        raise FileNotFoundError("No existe la fuente de internet: {}".format(ruta))
    opciones = dict(configuracion_fuente["read_options"])
    if opciones.get("dtype") != "string" or opciones.get("keep_default_na") is not False:
        raise ValueError("Internet requiere dtype: string y keep_default_na: false.")
    if opciones.get("na_values") != [""]:
        raise ValueError("Solo los vacios se declaran faltantes; el literal NA debe conservarse.")
    tamano = opciones.get("chunksize")
    if type(tamano) is not int or tamano <= 0:
        raise ValueError("Internet requiere un chunksize entero positivo.")
    if any(nombre in opciones for nombre in ("skiprows", "skipfooter", "nrows", "usecols", "index_col", "header")):
        raise ValueError("La extraccion debe recorrer el CSV completo y conservar sus columnas.")

    # El encabezado se valida antes de pandas para no ocultar duplicados.
    with ruta.open("r", encoding=opciones["encoding"], newline="") as archivo:
        encabezados = next(csv.reader(archivo, delimiter=opciones["sep"]), [])
    repetidos = [nombre for nombre, cantidad in Counter(encabezados).items() if cantidad > 1]
    if repetidos:
        raise ValueError("El CSV de internet repite encabezados: {}".format(repetidos))
    faltantes = sorted(set(configuracion_fuente["required_columns"]) - set(encabezados))
    if faltantes:
        raise ValueError("Faltan columnas de internet obligatorias: {}".format(faltantes))

    def recorrer() -> Generator[pd.DataFrame, None, None]:
        """Abrir al iterar y cerrar el lector al terminar o cerrar el generador."""
        LOGGER.info("Leyendo internet por bloques de %s: %s", tamano, ruta.name)
        leidas = 0
        # El context manager libera el archivo incluso si la limpieza falla.
        with pd.read_csv(ruta, **opciones) as lector:
            for numero, bloque in enumerate(lector, 1):
                if bloque.empty:
                    continue
                bloque.attrs["origen_csv"] = {
                    "archivo": str(ruta), "separador": opciones["sep"],
                    "codificacion": opciones["encoding"], "chunksize": tamano,
                    "bloque": numero, "registro_inicial": leidas + 1,
                    "fecha_descarga": None,
                }
                leidas += len(bloque)
                yield bloque
        if leidas == 0:
            raise ValueError("El archivo de internet no contiene registros.")
    return recorrer()
