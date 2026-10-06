"""Leer el catalogo DIVIPOLA conservando sus valores y el archivo Bronze."""

import csv
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


LOGGER = logging.getLogger(__name__)


def extraer_divipola(
    configuracion_fuente: Mapping[str, Any], raiz_proyecto: Path
) -> pd.DataFrame:
    """Leer todas las filas del CSV; la limpieza se realiza en otro modulo."""
    if configuracion_fuente.get("file_type") != "csv":
        raise ValueError("DIVIPOLA debe declarar file_type: csv.")
    ruta = Path(configuracion_fuente["path"])
    if not ruta.is_absolute():
        ruta = Path(raiz_proyecto) / ruta
    ruta = ruta.resolve()
    if not ruta.is_file():
        raise FileNotFoundError("No existe el catalogo DIVIPOLA: {}".format(ruta))

    # Copiar las opciones evita cambiar la configuracion utilizada por main.
    opciones = dict(configuracion_fuente["read_options"])
    if opciones.get("dtype") != "string" or opciones.get("keep_default_na") is not False:
        raise ValueError("DIVIPOLA requiere dtype: string y keep_default_na: false.")
    # La extraccion entrega una tabla completa y conserva el orden del CSV.
    if any(nombre in opciones for nombre in (
        "chunksize", "skiprows", "skipfooter", "nrows", "usecols", "index_col", "header"
    )):
        raise ValueError("DIVIPOLA debe leerse completo, con su encabezado original.")

    # Revisar el encabezado ANTES de pandas impide que su renombrado automatico
    # oculte columnas repetidas. Nunca abrimos la fuente en modo de escritura.
    with ruta.open("r", encoding=opciones["encoding"], newline="") as archivo:
        encabezados = next(csv.reader(archivo, delimiter=opciones["sep"]), [])
    repetidos = [nombre for nombre, cantidad in Counter(encabezados).items() if cantidad > 1]
    if repetidos:
        raise ValueError("El CSV DIVIPOLA repite encabezados: {}".format(repetidos))
    faltantes = sorted(set(configuracion_fuente["required_columns"]) - set(encabezados))
    if faltantes:
        raise ValueError("Faltan columnas DIVIPOLA obligatorias: {}".format(faltantes))

    LOGGER.info("Leyendo el catalogo territorial: %s", ruta.name)
    datos = pd.read_csv(ruta, **opciones)
    if datos.empty:
        raise ValueError("El catalogo DIVIPOLA no contiene registros.")
    # El archivo no contiene una fecha de vigencia. El nombre o la fecha del
    # sistema de archivos no prueban su validez para cada anio del panel.
    datos.attrs["origen_csv"] = {
        "archivo": str(ruta), "codificacion": opciones["encoding"],
        "separador": opciones["sep"], "fecha_actualizacion_fuente": None,
        "fecha_descarga": None, "vigencia_historica_verificada": False,
    }
    LOGGER.info("Extraidos %s territorios y %s columnas DIVIPOLA", len(datos), len(datos.columns))
    return datos
