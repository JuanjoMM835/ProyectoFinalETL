"""Guardar indicadores exploratorios en Parquet y CSV con evidencia verificable."""

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


def _validar_staging_gold(staging: Path, raiz: Path) -> None:
    """Verificar el destino absoluto antes de cualquier eliminación recursiva."""
    resuelta = staging.resolve()
    if (resuelta != staging or resuelta.parent != raiz
            or not resuelta.name.startswith(".gold_staging_")):
        raise ValueError(f"El staging Gold no es seguro: {staging}")


def _verificar_csv(datos: pd.DataFrame, archivo: Path, opciones: Mapping) -> None:
    """Controlar filas, columnas, faltantes y precisión de la copia CSV.

    CSV no conserva los tipos de pandas. Se relee todo como texto para proteger
    los ceros iniciales y el literal NA; los enteros se comparan exactamente sin
    pasarlos por float. Solo los números de tipo flotante admiten una tolerancia
    pequeña, necesaria al convertir una representación decimal de nuevo a binario.
    """
    original = datos.reset_index(drop=True)
    recuperado = pd.read_csv(
        archivo, sep=opciones["sep"], encoding=opciones["encoding"], dtype="string",
        keep_default_na=False, na_values=[""], skip_blank_lines=False, low_memory=False,
    )
    if list(recuperado.columns) != list(original.columns) or len(recuperado) != len(original):
        raise ValueError("La relectura CSV alteró las columnas o filas Gold.")
    pd.testing.assert_frame_equal(original.isna(), recuperado.isna(), check_exact=True)
    for columna in original.columns:
        valores = original[columna]
        if (columna.startswith("codigo_") or "__codigo_" in columna) and not isinstance(valores.dtype, pd.StringDtype):
            raise ValueError(f"El código {columna} debe conservar su tipo string antes de exportar.")
        presentes = valores.notna()
        esperado, observado = valores.loc[presentes], recuperado.loc[presentes, columna]
        if pd.api.types.is_float_dtype(valores.dtype):
            observado_numerico = pd.to_numeric(observado, errors="raise").astype("Float64")
            pd.testing.assert_series_equal(
                esperado.astype("Float64"), observado_numerico, check_exact=False,
                check_names=False, rtol=1e-12, atol=1e-12,
            )
        else:
            # Incluye texto, booleanos e Int64: ningún entero pierde dígitos.
            pd.testing.assert_series_equal(
                esperado.astype("string"), observado, check_exact=True, check_names=False,
            )


def exportar_gold(
    datos: pd.DataFrame, reporte: Dict[str, Any], metadata: Dict[str, Any],
    configuracion: Mapping[str, Any], raiz_proyecto: Path,
) -> Dict[str, Any]:
    """Publicar indicadores y reportes preparados, sin recalcular ni mutar entradas.

    Se preparan cuatro archivos y se verifican ambas representaciones de datos.
    Los reemplazos usan respaldos y rollback; la metadata se publica al final.
    El estado exploratorio o de aceptación procede del reporte recibido, nunca
    de la mera existencia de un archivo en la carpeta Gold.
    """
    if not isinstance(datos, pd.DataFrame):
        raise TypeError("Los indicadores Gold deben ser un DataFrame de pandas.")
    if not isinstance(reporte, Mapping) or not isinstance(metadata, Mapping):
        raise TypeError("El reporte y la metadata Gold deben ser mappings.")
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
    destinos = {}
    for nombre, opcion, extension, carpeta in (
        ("indicadores_gold", "indicators_gold", ".parquet", gold),
        ("indicadores_gold_csv", "indicators_gold_csv", ".csv", gold),
        ("reporte_indicadores", "gold_quality_report", ".json", logs),
        ("metadata_indicadores", "gold_metadata", ".json", logs),
    ):
        destinos[nombre] = (carpeta / _validar_nombre(outputs[opcion], extension, opcion)).resolve()

    # Mantener intacto el panel de entrada y los manifiestos de etapas anteriores.
    archivos_protegidos = set()
    for opcion, predeterminado, extension, carpeta in (
        ("integration_panel", "panel_integrado_exploratorio.parquet", ".parquet", gold),
        ("integration_quality_report", "reporte_integracion.json", ".json", logs),
        ("integration_metadata", "metadata_integracion.json", ".json", logs),
        ("quality_report", "reporte_calidad.json", ".json", logs),
        ("execution_metadata", "metadata_ejecucion.json", ".json", logs),
    ):
        archivos_protegidos.add(
            (carpeta / _validar_nombre(outputs.get(opcion, predeterminado), extension, opcion)).resolve()
        )
    for fuente in configuracion.get("sources", {}).values():
        if isinstance(fuente, Mapping) and fuente.get("path"):
            archivos_protegidos.add((raiz / fuente["path"]).resolve())
    config_registrada = metadata.get("configuracion", {})
    if isinstance(config_registrada, Mapping) and config_registrada.get("archivo"):
        archivos_protegidos.add((raiz / config_registrada["archivo"]).resolve())
    normalizadas = [os.path.normcase(str(ruta)) for ruta in destinos.values()]
    if len(set(normalizadas)) != len(normalizadas):
        raise ValueError("Dos salidas Gold apuntan al mismo archivo.")
    for destino in destinos.values():
        if not _esta_dentro(destino, raiz) or any(_esta_dentro(destino, carpeta) for carpeta in protegidas):
            raise ValueError(f"Gold no puede escribir fuera del proyecto ni en Bronze/Silver: {destino}")
        if destino in archivos_protegidos:
            raise ValueError(f"Gold intenta reemplazar una entrada o un manifiesto anterior: {destino}")
        if destino.exists() and not destino.is_file():
            raise ValueError(f"Una salida Gold coincide con una carpeta: {destino}")
        if any(_esta_dentro(carpeta, destino) for carpeta in (gold, logs)):
            raise ValueError(f"Una salida Gold coincide con una carpeta necesaria: {destino}")
    opciones = outputs.get("csv_options", {})
    separador, codificacion = opciones.get("sep", ","), opciones.get("encoding", "utf-8-sig")
    if (not isinstance(separador, str) or len(separador) != 1 or separador in "\r\n"
            or not isinstance(codificacion, str) or not codificacion
            or opciones.get("index", False) is not False):
        raise ValueError("CSV requiere separador de un carácter, codificación e index=False.")
    opciones_csv = {"sep": separador, "encoding": codificacion, "index": False,
                    "float_format": "%.17g", "na_rep": ""}

    metadata_final = deepcopy(dict(metadata))
    staging = Path(tempfile.mkdtemp(prefix=".gold_staging_", dir=str(raiz))).resolve()
    _validar_staging_gold(staging, raiz)
    preparados, respaldos = {}, {}
    publicados, carpetas_creadas = [], []
    conservar_recuperacion = False
    try:
        LOGGER.info("Preparando y verificando indicadores Parquet, CSV y reportes Gold.")
        reporte_temporal = staging / "reporte_indicadores.json"
        _escribir_json(reporte, reporte_temporal)
        preparados["reporte_indicadores"] = reporte_temporal
        parquet_temporal = staging / "indicadores.parquet"
        datos.to_parquet(parquet_temporal, engine="pyarrow", index=False, compression="snappy")
        pd.testing.assert_frame_equal(
            datos.reset_index(drop=True), pd.read_parquet(parquet_temporal, engine="pyarrow"),
            check_exact=True, check_dtype=True,
        )
        preparados["indicadores_gold"] = parquet_temporal
        csv_temporal = staging / "indicadores.csv"
        datos.to_csv(csv_temporal, **opciones_csv)
        _verificar_csv(datos, csv_temporal, opciones_csv)
        preparados["indicadores_gold_csv"] = csv_temporal
        esquema = [{"nombre": str(columna), "tipo": str(tipo)}
                   for columna, tipo in zip(datos.columns, datos.dtypes)]
        metadata_final["salidas"] = {
            nombre: {"archivo": str(destinos[nombre]), "filas": int(len(datos)),
                     "columnas": deepcopy(esquema), "tamano_bytes": int(preparados[nombre].stat().st_size),
                     "sha256": _huella_sha256(preparados[nombre])}
            for nombre in ("indicadores_gold", "indicadores_gold_csv")
        }
        # En CSV el esquema descrito es lógico; su relectura necesita tipos explícitos.
        metadata_final["salidas"]["indicadores_gold_csv"]["opciones_csv"] = deepcopy(opciones_csv)
        metadata_final["reporte_indicadores"] = {
            "archivo": str(destinos["reporte_indicadores"]),
            "tamano_bytes": int(reporte_temporal.stat().st_size),
            "sha256": _huella_sha256(reporte_temporal),
        }
        metadata_final["metadata_indicadores"] = {"archivo": str(destinos["metadata_indicadores"])}
        # Cierre de preparación y verificación; la publicación sucede inmediatamente después.
        metadata_final["fin_exportacion_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        metadata_temporal = staging / "metadata_indicadores.json"
        _escribir_json(metadata_final, metadata_temporal)
        preparados["metadata_indicadores"] = metadata_temporal

        for carpeta in dict.fromkeys((gold, logs)):
            _crear_carpetas(carpeta, carpetas_creadas)
        for numero, (nombre, destino) in enumerate(destinos.items(), start=1):
            if destino.exists():
                respaldo = staging / f"respaldo_{numero:02d}"
                shutil.copy2(destino, respaldo)
                respaldos[nombre] = respaldo
        # El orden de destinos publica metadata después de los datos y su reporte.
        for nombre, destino in destinos.items():
            preparados[nombre].replace(destino)
            publicados.append(nombre)
        LOGGER.info("Gold publicada y verificada: %s filas en Parquet y CSV.", len(datos))
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
            conservar_recuperacion = True
            LOGGER.critical("Rollback Gold incompleto; respaldos en %s.", staging)
            raise RuntimeError(
                f"Gold requiere recuperación desde {staging}: " + "; ".join(fallos_recuperacion)
            ) from error_publicacion
        if publicados:
            LOGGER.warning("Publicación Gold revertida; salidas anteriores restauradas.")
        for carpeta in reversed(carpetas_creadas):
            try:
                carpeta.rmdir()
            except OSError:
                pass  # Conservar carpetas con otros archivos del usuario.
        raise
    finally:
        if not conservar_recuperacion:
            _validar_staging_gold(staging, raiz)
            shutil.rmtree(staging)
