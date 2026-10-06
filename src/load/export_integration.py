"""Publicar el panel integrado exploratorio y su evidencia de calidad.

El panel es un producto intermedio anterior al cálculo de indicadores. Este
módulo guarda datos ya preparados y conserva las salidas de Bronze y Silver.
"""

from copy import deepcopy
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, Mapping

import pandas as pd

from src.load.export_results import (
    _crear_carpetas, _escribir_json, _esta_dentro, _huella_sha256,
    _resolver_carpeta, _validar_nombre,
)


LOGGER = logging.getLogger(__name__)


def _validar_staging_integracion(staging: Path, raiz: Path) -> None:
    """Comprobar la ruta absoluta antes de cualquier eliminación recursiva."""
    resuelta = staging.resolve()
    if (resuelta != staging or resuelta.parent != raiz
            or not resuelta.name.startswith(".integration_staging_")):
        raise ValueError(f"El staging de integración no es seguro: {staging}")


def exportar_integracion(
    panel: pd.DataFrame, reporte: Dict[str, Any], metadata: Dict[str, Any],
    configuracion: Mapping[str, Any], raiz_proyecto: Path,
) -> Dict[str, Any]:
    """Guardar un Parquet y dos JSON sin modificar los objetos de entrada.

    Antes de reemplazar archivos se prepara y verifica el conjunto completo.
    La metadata se publica al final y, ante un fallo de publicación, se restaura
    la versión anterior. No se calculan indicadores ni controles en esta etapa.
    """
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("El panel integrado debe ser un DataFrame de pandas.")
    if not isinstance(reporte, Mapping) or not isinstance(metadata, Mapping):
        raise TypeError("El reporte y la metadata de integración deben ser mappings.")
    raiz = Path(raiz_proyecto).resolve(strict=True)
    if not raiz.is_dir():
        raise ValueError("La raíz del proyecto debe ser una carpeta existente.")
    paths, outputs = configuracion["paths"], configuracion["outputs"]
    gold = _resolver_carpeta(paths["gold_dir"], raiz, "paths.gold_dir")
    logs = _resolver_carpeta(paths["logs_dir"], raiz, "paths.logs_dir")
    carpetas_protegidas = [
        _resolver_carpeta(paths.get("bronze_dir", "data/bronze"), raiz, "paths.bronze_dir"),
        _resolver_carpeta(paths.get("silver_dir", "data/silver"), raiz, "paths.silver_dir"),
    ]
    destinos = {
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

    # El reporte Silver y su manifiesto siguen describiendo los cuatro Parquet.
    # Tampoco se reemplazan los archivos reservados para los futuros indicadores.
    archivos_protegidos = {
        (logs / _validar_nombre(outputs.get("quality_report", "reporte_calidad.json"), ".json", "quality_report")).resolve(),
        (logs / _validar_nombre(outputs.get("execution_metadata", "metadata_ejecucion.json"), ".json", "execution_metadata")).resolve(),
    }
    for opcion, extension in (("indicators_gold", ".parquet"), ("indicators_gold_csv", ".csv")):
        if opcion in outputs:
            archivos_protegidos.add((gold / _validar_nombre(outputs[opcion], extension, opcion)).resolve())
    for fuente in configuracion.get("sources", {}).values():
        if isinstance(fuente, Mapping) and fuente.get("path"):
            archivos_protegidos.add((raiz / fuente["path"]).resolve())
    config_registrada = metadata.get("configuracion", {})
    if isinstance(config_registrada, Mapping) and config_registrada.get("archivo"):
        archivos_protegidos.add((raiz / config_registrada["archivo"]).resolve())

    normalizadas = [os.path.normcase(str(ruta)) for ruta in destinos.values()]
    if len(set(normalizadas)) != len(normalizadas):
        raise ValueError("Dos salidas de integración apuntan al mismo archivo.")
    for destino in destinos.values():
        if not _esta_dentro(destino, raiz):
            raise ValueError(f"Una salida de integración queda fuera del proyecto: {destino}")
        if any(_esta_dentro(destino, carpeta) for carpeta in carpetas_protegidas):
            raise ValueError(f"La integración no puede escribir en Bronze ni Silver: {destino}")
        if destino in archivos_protegidos:
            raise ValueError(f"La integración intenta reemplazar una entrada u otra salida: {destino}")
        if destino.exists() and not destino.is_file():
            raise ValueError(f"Una salida de integración coincide con una carpeta: {destino}")
        if any(_esta_dentro(carpeta, destino) for carpeta in (gold, logs)):
            raise ValueError(f"Una salida coincide con una carpeta necesaria: {destino}")

    metadata_final = deepcopy(dict(metadata))
    staging = Path(tempfile.mkdtemp(prefix=".integration_staging_", dir=str(raiz))).resolve()
    _validar_staging_integracion(staging, raiz)
    preparados, respaldos = {}, {}
    publicados, carpetas_creadas = [], []
    conservar_recuperacion = False
    try:
        LOGGER.info("Preparando el panel integrado exploratorio y sus reportes.")
        reporte_temporal = staging / "reporte_integracion.json"
        _escribir_json(reporte, reporte_temporal)
        preparados["reporte_integracion"] = reporte_temporal
        panel_temporal = staging / "panel_integrado.parquet"
        panel.to_parquet(panel_temporal, engine="pyarrow", index=False, compression="snappy")
        recuperado = pd.read_parquet(panel_temporal, engine="pyarrow")
        # El índice técnico se omite; la identidad territorial queda en columnas.
        pd.testing.assert_frame_equal(
            panel.reset_index(drop=True), recuperado, check_exact=True, check_dtype=True
        )
        preparados["panel_integrado"] = panel_temporal
        metadata_final["salidas"] = {
            "panel_integrado": {
                "archivo": str(destinos["panel_integrado"]), "filas": int(len(panel)),
                "columnas": [{"nombre": str(columna), "tipo": str(tipo)}
                             for columna, tipo in zip(panel.columns, panel.dtypes)],
                "tamano_bytes": int(panel_temporal.stat().st_size),
                "sha256": _huella_sha256(panel_temporal),
            },
        }
        metadata_final["reporte_integracion"] = {
            "archivo": str(destinos["reporte_integracion"]),
            "tamano_bytes": int(reporte_temporal.stat().st_size),
            "sha256": _huella_sha256(reporte_temporal),
        }
        # La metadata describe su ubicación, sin intentar calcular su propio hash.
        metadata_final["metadata_integracion"] = {
            "archivo": str(destinos["metadata_integracion"]),
        }
        metadata_final["fin_exportacion_utc"] = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        metadata_temporal = staging / "metadata_integracion.json"
        _escribir_json(metadata_final, metadata_temporal)
        preparados["metadata_integracion"] = metadata_temporal

        # Preparar todos los respaldos antes de publicar la primera salida.
        for carpeta in dict.fromkeys((gold, logs)):
            _crear_carpetas(carpeta, carpetas_creadas)
        for numero, (nombre, destino) in enumerate(destinos.items(), start=1):
            if destino.exists():
                respaldo = staging / f"respaldo_{numero:02d}"
                shutil.copy2(destino, respaldo)
                respaldos[nombre] = respaldo
        LOGGER.info("Panel verificado: %s filas. Publicando metadata al final.", len(panel))
        for nombre, destino in destinos.items():
            preparados[nombre].replace(destino)
            publicados.append(nombre)
        LOGGER.info("Panel integrado exploratorio y evidencia publicados correctamente.")
        return metadata_final
    except BaseException as error_publicacion:
        fallos_recuperacion = []
        for nombre in reversed(publicados):
            try:
                if nombre in respaldos:
                    respaldos[nombre].replace(destinos[nombre])
                else:
                    destinos[nombre].unlink()
            except OSError as error_recuperacion:
                fallos_recuperacion.append(f"{destinos[nombre]}: {error_recuperacion}")
        if fallos_recuperacion:
            # Ante un fallo del sistema, conservar respaldos permite recuperación manual.
            conservar_recuperacion = True
            LOGGER.critical("Rollback incompleto de integración; respaldos en %s.", staging)
            raise RuntimeError(
                f"La integración requiere recuperación desde {staging}: "
                + "; ".join(fallos_recuperacion)
            ) from error_publicacion
        if publicados:
            LOGGER.warning("Publicación de integración revertida; salidas anteriores restauradas.")
        for carpeta in reversed(carpetas_creadas):
            try:
                carpeta.rmdir()
            except OSError:
                # Conservar las carpetas que contienen otros archivos del usuario.
                pass
        raise
    finally:
        if not conservar_recuperacion:
            _validar_staging_integracion(staging, raiz)
            shutil.rmtree(staging)
