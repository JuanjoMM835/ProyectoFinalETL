"""Leer una ejecución Silver publicada, verificando su evidencia antes de integrar.

Esta etapa consume cuatro Parquet y dos JSON. No vuelve a extraer Bronze ni
interpreta la fecha de un archivo como vigencia histórica de un territorio.
"""

from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any, Dict, Mapping, Tuple

import pandas as pd

from src.load.execution_metadata import huella_archivo
from src.load.export_results import SALIDAS_TABLAS, _resolver_carpeta, _validar_nombre


LOGGER = logging.getLogger(__name__)


def _constante_invalida(valor: str) -> None:
    """Rechazar NaN e infinitos literales que JSON estándar no admite."""
    raise ValueError(f"Constante no válida en JSON Silver: {valor}")


def _decimal_json(valor: str) -> float:
    """Rechazar también exponentes que desbordan a infinito al leer JSON."""
    numero = float(valor)
    if not math.isfinite(numero):
        raise ValueError(f"Número no finito en JSON Silver: {valor}")
    return numero


def _objeto_json(pares: list) -> Dict[str, Any]:
    """Evitar que una clave duplicada cambie silenciosamente el manifiesto."""
    objeto = {}
    for clave, valor in pares:
        if clave in objeto:
            raise ValueError(f"Clave duplicada en JSON Silver: {clave}")
        objeto[clave] = valor
    return objeto


def _leer_json(archivo: Path) -> Dict[str, Any]:
    """Leer objetos JSON UTF-8 con validación estricta de números y claves."""
    with archivo.open("r", encoding="utf-8") as lector:
        contenido = json.load(
            lector, parse_constant=_constante_invalida,
            parse_float=_decimal_json, object_pairs_hook=_objeto_json,
        )
    if not isinstance(contenido, dict):
        raise ValueError(f"El JSON Silver debe contener un objeto: {archivo}")
    return contenido


def _validar_ruta_registrada(registro: Mapping, actual: Path, raiz: Path) -> str:
    """Comparar la salida esperada y conservar rutas antiguas como diagnóstico.

    Una copia del proyecto puede estar en otra carpeta: en ese caso se admite
    la ruta absoluta antigua si conserva el nombre de archivo. Nunca se abre
    esa ruta antigua; solo se leen los destinos configurados de la raíz actual.
    """
    if not isinstance(registro, Mapping):
        raise ValueError(f"Falta el registro de la salida Silver: {actual.name}")
    registrado = registro.get("archivo")
    if not isinstance(registrado, str) or not registrado:
        raise ValueError(f"Falta la ruta registrada de Silver: {actual.name}")
    if not (PureWindowsPath(registrado).is_absolute() or PurePosixPath(registrado).is_absolute()):
        raise ValueError(f"La ruta registrada de Silver debe ser absoluta: {registrado}")
    nombre_registrado = registrado.replace("\\", "/").rsplit("/", 1)[-1]
    if os.path.normcase(nombre_registrado) != os.path.normcase(actual.name):
        raise ValueError(f"El nombre registrado no corresponde a la salida: {actual.name}")
    anterior = Path(registrado)
    if anterior.is_absolute():
        anterior = anterior.resolve()
        # Dentro de la raíz actual no hay traslado que justifique otra carpeta.
        if (anterior == raiz or raiz in anterior.parents) and anterior != actual:
            raise ValueError(f"La ruta registrada no corresponde al destino configurado: {actual}")
    return registrado


def _verificar_archivo(archivo: Path, registro: Mapping, raiz: Path) -> Dict[str, Any]:
    """Comprobar tamaño y SHA-256 antes de confiar en un Parquet o reporte."""
    registrado = _validar_ruta_registrada(registro, archivo, raiz)
    tamano = registro.get("tamano_bytes")
    huella = registro.get("sha256")
    if type(tamano) is not int or tamano < 0:
        raise ValueError(f"Tamaño registrado no válido: {archivo.name}")
    if not isinstance(huella, str) or not re.fullmatch(r"[0-9a-f]{64}", huella):
        raise ValueError(f"SHA-256 registrado no válido: {archivo.name}")
    if archivo.stat().st_size != tamano or huella_archivo(archivo) != huella:
        raise ValueError(f"La integridad de Silver no coincide con su metadata: {archivo.name}")
    return {
        "archivo_actual": str(archivo), "archivo_registrado": registrado,
        "sha256": huella, "tamano_bytes": tamano,
    }


def leer_silver(
    configuracion: Mapping[str, Any], raiz_proyecto: Path,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any]]:
    """Devolver tablas Silver verificadas y la procedencia de su ejecución.

    Se conserva el índice y los tipos que recupera pyarrow: no se convierten
    códigos a números, no se rellenan faltantes y no se limpia de nuevo. El
    manifiesto debe corresponder a los archivos, esquema y contrato actuales.
    La configuración puede incorporar nuevas salidas de integración; por eso
    no se exige que su huella coincida con la configuración anterior de Silver.
    """
    raiz = Path(raiz_proyecto).resolve(strict=True)
    if not raiz.is_dir():
        raise ValueError("La raíz de Silver debe ser una carpeta existente.")
    paths, outputs = configuracion["paths"], configuracion["outputs"]
    silver = _resolver_carpeta(paths["silver_dir"], raiz, "paths.silver_dir")
    logs = _resolver_carpeta(paths["logs_dir"], raiz, "paths.logs_dir")
    protegidas = [
        _resolver_carpeta(paths.get("bronze_dir", "data/bronze"), raiz, "paths.bronze_dir"),
        _resolver_carpeta(paths.get("gold_dir", "data/gold"), raiz, "paths.gold_dir"),
    ]
    archivos = {
        nombre: (silver / _validar_nombre(outputs[opcion], ".parquet", opcion)).resolve()
        for nombre, opcion in SALIDAS_TABLAS.items()
    }
    archivos["metadata"] = (
        logs / _validar_nombre(outputs["execution_metadata"], ".json", "execution_metadata")
    ).resolve()
    archivos["reporte"] = (
        logs / _validar_nombre(outputs["quality_report"], ".json", "quality_report")
    ).resolve()
    normalizadas = [os.path.normcase(str(ruta)) for ruta in archivos.values()]
    if len(set(normalizadas)) != len(normalizadas):
        raise ValueError("Dos entradas Silver apuntan al mismo archivo.")
    for archivo in archivos.values():
        if raiz not in archivo.parents or any(
            archivo == protegida or protegida in archivo.parents for protegida in protegidas
        ):
            raise ValueError(f"Una entrada Silver queda fuera de su ubicación permitida: {archivo}")
        if not archivo.is_file():
            raise FileNotFoundError(f"No existe el archivo Silver publicado: {archivo}")

    LOGGER.info("Leyendo el manifiesto y verificando los archivos Silver.")
    huella_metadata = huella_archivo(archivos["metadata"])
    metadata = _leer_json(archivos["metadata"])
    contrato = configuracion["project"]["data_contract"]["version"]
    ejecucion = metadata.get("ejecucion_id")
    if metadata.get("etapa") != "silver" or not isinstance(ejecucion, str) or not ejecucion:
        raise ValueError("La metadata no identifica una ejecución Silver válida.")
    if metadata.get("version_contrato") != contrato:
        raise ValueError("El contrato de Silver no coincide con la configuración actual.")
    salidas = metadata.get("salidas")
    if not isinstance(salidas, dict) or set(salidas) != set(SALIDAS_TABLAS):
        raise ValueError("La metadata debe identificar exactamente las cuatro tablas Silver.")
    _validar_ruta_registrada(metadata.get("metadata_ejecucion"), archivos["metadata"], raiz)
    registro_reporte = _verificar_archivo(archivos["reporte"], metadata.get("reporte_calidad"), raiz)
    reporte = _leer_json(archivos["reporte"])
    if (reporte.get("etapa") != "silver" or reporte.get("ejecucion_id") != ejecucion
            or reporte.get("version_contrato") != contrato):
        raise ValueError("El reporte de calidad no corresponde a la ejecución y contrato Silver.")
    if huella_archivo(archivos["reporte"]) != registro_reporte["sha256"]:
        raise ValueError("El reporte Silver cambió durante su lectura.")

    tablas, entradas = {}, {}
    for nombre in SALIDAS_TABLAS:
        registro = salidas[nombre]
        evidencia = _verificar_archivo(archivos[nombre], registro, raiz)
        tabla = pd.read_parquet(archivos[nombre], engine="pyarrow")
        filas = registro.get("filas")
        esquema = [{"nombre": str(columna), "tipo": str(tipo)}
                   for columna, tipo in zip(tabla.columns, tabla.dtypes)]
        if type(filas) is not int or filas < 0 or len(tabla) != filas:
            raise ValueError(f"Las filas no coinciden con la metadata Silver: {nombre}")
        if registro.get("columnas") != esquema:
            raise ValueError(f"El esquema o los tipos no coinciden con la metadata Silver: {nombre}")
        if huella_archivo(archivos[nombre]) != evidencia["sha256"]:
            raise ValueError(f"El Parquet Silver cambió durante su lectura: {nombre}")
        evidencia["filas"] = filas
        tablas[nombre], entradas[nombre] = tabla, evidencia
        LOGGER.info("Silver %s verificada: %s filas.", nombre, filas)
    if huella_archivo(archivos["metadata"]) != huella_metadata:
        raise ValueError("La metadata Silver cambió durante la lectura de sus salidas.")

    fuentes_reporte = reporte.get("fuentes", {})
    if not isinstance(fuentes_reporte, dict):
        raise ValueError("Las fuentes del reporte Silver deben formar un objeto JSON.")
    fuente_catalogo = fuentes_reporte.get("divipola", {})
    if not isinstance(fuente_catalogo, dict):
        raise ValueError("La evidencia DIVIPOLA del reporte Silver no es válida.")
    reporte_catalogo = fuente_catalogo.get("reporte_transformacion", {})
    if not isinstance(reporte_catalogo, dict) or not isinstance(reporte_catalogo.get("origen_csv", {}), dict):
        raise ValueError("El origen DIVIPOLA del reporte Silver no es válido.")
    origen_catalogo = deepcopy(reporte_catalogo.get("origen_csv", {}))
    # Un código que existe en el catálogo actual no demuestra su vigencia anual.
    # Solo una evidencia temporal explícita, revisada en otra etapa, puede hacerlo.
    origen_catalogo["vigencia_historica_verificada"] = False
    tablas["divipola"].attrs["origen_csv"] = origen_catalogo
    tablas["divipola"].attrs["vigencia_historica_verificada"] = False
    procedencia = {
        "ejecucion_silver": ejecucion, "version_contrato": contrato,
        "entradas_silver": entradas,
        "metadata_silver": {"archivo": str(archivos["metadata"]), "sha256": huella_metadata},
        "reporte_calidad_silver": {
            "archivo": str(archivos["reporte"]), "sha256": registro_reporte["sha256"],
        },
        "catalogo_temporal": {
            "vigencia_historica_verificada": False,
            "anio_inicio": None, "anio_fin": None, "referencia": None,
            "motivo": "CSV disponible sin vigencia anual documentada",
        },
    }
    return tablas, procedencia
