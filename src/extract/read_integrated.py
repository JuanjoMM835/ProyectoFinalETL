"""Leer el panel intermedio verificado, sin volver a recorrer Bronze ni Silver."""

from copy import deepcopy
import logging
import os
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

import pandas as pd

from src.extract.read_silver import _leer_json, _validar_ruta_registrada, _verificar_archivo
from src.load.execution_metadata import huella_archivo
from src.load.export_results import _esta_dentro, _resolver_carpeta, _validar_nombre


LOGGER = logging.getLogger(__name__)


def leer_panel_integrado(
    configuracion: Mapping[str, Any], raiz_proyecto: Path,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Devolver el panel y la evidencia de los tres archivos de integración.

    Los tipos, códigos y faltantes se recuperan del Parquet sin transformarlos.
    Se comprueban identidad de ejecución, contrato, periodo, contenido y esquema.
    Agregar salidas Gold al YAML no invalida por sí mismo la integración anterior:
    se valida el contrato y periodo, sin exigir la antigua huella del YAML.
    """
    raiz = Path(raiz_proyecto).resolve(strict=True)
    if not raiz.is_dir():
        raise ValueError("La raíz del proyecto debe ser una carpeta existente.")
    paths, outputs = configuracion["paths"], configuracion["outputs"]
    gold = _resolver_carpeta(paths["gold_dir"], raiz, "paths.gold_dir")
    logs = _resolver_carpeta(paths["logs_dir"], raiz, "paths.logs_dir")
    protegidas = [
        _resolver_carpeta(paths.get("bronze_dir", "data/bronze"), raiz, "paths.bronze_dir"),
        _resolver_carpeta(paths.get("silver_dir", "data/silver"), raiz, "paths.silver_dir"),
    ]
    archivos = {
        "panel_integrado": (
            gold / _validar_nombre(outputs["integration_panel"], ".parquet", "integration_panel")
        ).resolve(),
        "reporte_integracion": (
            logs / _validar_nombre(outputs["integration_quality_report"], ".json", "integration_quality_report")
        ).resolve(),
        "metadata_integracion": (
            logs / _validar_nombre(outputs["integration_metadata"], ".json", "integration_metadata")
        ).resolve(),
    }
    normalizadas = [os.path.normcase(str(ruta)) for ruta in archivos.values()]
    if len(set(normalizadas)) != len(normalizadas):
        raise ValueError("Dos entradas de integración coinciden en el mismo archivo.")
    for archivo in archivos.values():
        if not _esta_dentro(archivo, raiz) or any(_esta_dentro(archivo, carpeta) for carpeta in protegidas):
            raise ValueError(f"El lector integrado no puede acceder a esa ruta: {archivo}")
        if not archivo.is_file():
            raise FileNotFoundError(f"Falta una salida de integración publicada: {archivo}")

    LOGGER.info("Verificando el manifiesto y las salidas del panel integrado.")
    archivo_metadata = archivos["metadata_integracion"]
    huella_metadata = huella_archivo(archivo_metadata)
    metadata = _leer_json(archivo_metadata)
    ejecucion = metadata.get("ejecucion_id")
    contrato = configuracion["project"]["data_contract"]["version"]
    periodo = {"inicio": configuracion["processing"]["year_start"],
               "fin": configuracion["processing"]["year_end"]}
    if metadata.get("etapa") != "integracion" or not isinstance(ejecucion, str) or not ejecucion:
        raise ValueError("La metadata no identifica una ejecución de integración válida.")
    if metadata.get("version_contrato") != contrato or metadata.get("periodo") != periodo:
        raise ValueError("El contrato o periodo integrado no coincide con la configuración actual.")
    salidas = metadata.get("salidas")
    if not isinstance(salidas, dict) or set(salidas) != {"panel_integrado"}:
        raise ValueError("La metadata de integración debe describir exactamente un panel.")
    _validar_ruta_registrada(metadata.get("metadata_integracion"), archivo_metadata, raiz)
    evidencia_reporte = _verificar_archivo(
        archivos["reporte_integracion"], metadata.get("reporte_integracion"), raiz
    )
    reporte = _leer_json(archivos["reporte_integracion"])
    if (reporte.get("etapa") != "integracion" or reporte.get("ejecucion_id") != ejecucion
            or reporte.get("version_contrato") != contrato):
        raise ValueError("El reporte no corresponde a la ejecución y contrato del panel integrado.")
    # Las primeras ejecuciones registraron el periodo solo en metadata.
    if "periodo" in reporte and reporte["periodo"] != periodo:
        raise ValueError("El periodo del reporte integrado no coincide con la configuración.")
    aceptacion = reporte.get("aceptacion_panel")
    if not isinstance(aceptacion, dict):
        raise ValueError("El reporte integrado no contiene su estado de aceptación del panel.")

    registro_panel = salidas["panel_integrado"]
    evidencia_panel = _verificar_archivo(archivos["panel_integrado"], registro_panel, raiz)
    panel = pd.read_parquet(archivos["panel_integrado"], engine="pyarrow")
    filas = registro_panel.get("filas")
    esquema = [{"nombre": str(columna), "tipo": str(tipo)}
               for columna, tipo in zip(panel.columns, panel.dtypes)]
    if type(filas) is not int or filas < 0 or len(panel) != filas:
        raise ValueError("Las filas del panel integrado no coinciden con su metadata.")
    if registro_panel.get("columnas") != esquema:
        raise ValueError("Los tipos o columnas del panel integrado no coinciden con su metadata.")
    if "filas_panel" in reporte and reporte["filas_panel"] != filas:
        raise ValueError("El reporte de integración describe otra cantidad de filas.")
    if ("anio" not in panel or not pd.api.types.is_integer_dtype(panel["anio"].dtype)
            or panel["anio"].isna().any()
            or not panel["anio"].between(periodo["inicio"], periodo["fin"]).all()):
        raise ValueError("El panel integrado contiene años inválidos o fuera del periodo.")

    # Detectar sustituciones durante la lectura, sin reinterpretar los datos.
    for nombre, huella in (
        ("panel_integrado", evidencia_panel["sha256"]),
        ("reporte_integracion", evidencia_reporte["sha256"]),
        ("metadata_integracion", huella_metadata),
    ):
        if huella_archivo(archivos[nombre]) != huella:
            raise ValueError(f"La entrada integrada cambió durante su lectura: {nombre}")
    entradas = {
        "panel_integrado": {"archivo": str(archivos["panel_integrado"]),
                            "sha256": evidencia_panel["sha256"],
                            "tamano_bytes": evidencia_panel["tamano_bytes"]},
        "reporte_integracion": {"archivo": str(archivos["reporte_integracion"]),
                                "sha256": evidencia_reporte["sha256"],
                                "tamano_bytes": evidencia_reporte["tamano_bytes"]},
        "metadata_integracion": {"archivo": str(archivo_metadata), "sha256": huella_metadata,
                                 "tamano_bytes": int(archivo_metadata.stat().st_size)},
    }
    LOGGER.info("Panel integrado verificado: %s filas de la ejecución %s.", filas, ejecucion)
    return panel, {"ejecucion_integracion": ejecucion, "version_contrato": contrato,
                   "entradas_integracion": entradas, "aceptacion_panel": deepcopy(aceptacion)}
