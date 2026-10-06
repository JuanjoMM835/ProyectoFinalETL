"""Publicar las tablas Silver y sus reportes sin volver a transformar los datos.

La escritura se prepara en una carpeta temporal del proyecto. Solo cuando los
cuatro Parquet y ambos JSON están completos se reemplazan las salidas finales.
La metadata se publica al final para que describa una ejecución ya terminada.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Dict, Mapping

import pandas as pd


LOGGER = logging.getLogger(__name__)

# Los nombres internos del pipeline se relacionan con las opciones de YAML.
SALIDAS_TABLAS = {
    "educacion": "education_silver",
    "poblacion": "population_silver",
    "internet": "internet_silver",
    "divipola": "divipola_silver",
}


def _esta_dentro(ruta: Path, carpeta: Path) -> bool:
    """Comprobar pertenencia con componentes de ruta, nunca con prefijos de texto."""
    return ruta == carpeta or carpeta in ruta.parents


def _resolver_carpeta(valor, raiz: Path, opcion: str) -> Path:
    """Resolver una carpeta configurada y evitar salir del proyecto."""
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"La opción {opcion} debe indicar una carpeta.")
    ruta = (raiz / valor).resolve()
    if not _esta_dentro(ruta, raiz):
        raise ValueError(f"La carpeta {opcion} queda fuera del proyecto: {ruta}")
    if ruta.exists() and not ruta.is_dir():
        raise ValueError(f"La carpeta {opcion} coincide con un archivo: {ruta}")
    return ruta


def _validar_nombre(valor, extension: str, opcion: str) -> str:
    """Aceptar nombres de archivo simples, también seguros en Windows."""
    if not isinstance(valor, str) or not valor:
        raise ValueError(f"La salida {opcion} debe tener un nombre de archivo.")
    invalidos = '<>:"/\\|?*'
    if (
        valor in {".", ".."}
        or valor != valor.strip()
        or valor.endswith(".")
        or any(caracter in invalidos or ord(caracter) < 32 for caracter in valor)
        or Path(valor).suffix.lower() != extension
    ):
        raise ValueError(
            f"La salida {opcion} debe ser un nombre simple con extensión {extension}."
        )
    # Windows reserva estos nombres incluso cuando llevan una extensión.
    reservado = valor.split(".", 1)[0].upper()
    if reservado in {"CON", "PRN", "AUX", "NUL"} or reservado in {
        f"{prefijo}{numero}" for prefijo in ("COM", "LPT") for numero in range(1, 10)
    }:
        raise ValueError(f"El nombre de la salida {opcion} está reservado: {valor}")
    return valor


def _huella_sha256(archivo: Path) -> str:
    """Identificar el contenido publicado leyendo por bloques de un megabyte."""
    huella = hashlib.sha256()
    with archivo.open("rb") as lector:
        for bloque in iter(lambda: lector.read(1024 * 1024), b""):
            huella.update(bloque)
    return huella.hexdigest()


def _escribir_json(contenido: Mapping, archivo: Path) -> None:
    """Guardar JSON legible y rechazar NaN o infinitos que no admite el formato."""
    texto = json.dumps(contenido, ensure_ascii=False, indent=2, allow_nan=False)
    archivo.write_text(texto + "\n", encoding="utf-8")


def _crear_carpetas(carpeta: Path, creadas: list) -> None:
    """Registrar las carpetas nuevas para poder retirarlas si falla la publicación."""
    faltantes = []
    actual = carpeta
    while not actual.exists():
        faltantes.append(actual)
        actual = actual.parent
    if not actual.is_dir():
        raise ValueError(f"Una carpeta de salida tiene un archivo como antecesor: {actual}")
    for pendiente in reversed(faltantes):
        pendiente.mkdir()
        creadas.append(pendiente)


def _validar_staging(staging: Path, raiz: Path) -> None:
    """Verificar el destino absoluto antes de cualquier eliminación recursiva."""
    resuelta = staging.resolve()
    if (
        resuelta != staging
        or resuelta.parent != raiz
        or not resuelta.name.startswith(".silver_staging_")
    ):
        raise ValueError(f"La carpeta temporal no es un staging seguro del proyecto: {staging}")


def exportar_silver(
    tablas: Mapping[str, pd.DataFrame],
    reporte_calidad: Dict,
    metadata: Dict,
    configuracion: Mapping,
    raiz_proyecto: Path,
) -> Dict:
    """Exportar cuatro tablas y dos reportes, conservando los objetos recibidos.

    Aquí no se limpian filas ni se calculan controles de calidad: las tablas y el
    reporte deben llegar preparados desde las etapas anteriores. El resultado es
    una copia de la metadata enriquecida con rutas, esquemas, tamaños y huellas.

    Antes de publicar se releen los Parquet y se comparan exactamente con sus
    tablas de origen. El índice de pandas se descarta de forma deliberada: las
    llaves territoriales ya están en columnas y no dependen de ese índice.
    """
    if set(tablas) != set(SALIDAS_TABLAS):
        raise ValueError("Se requieren exactamente educacion, poblacion, internet y divipola.")
    if any(not isinstance(tabla, pd.DataFrame) for tabla in tablas.values()):
        raise TypeError("Cada tabla Silver debe ser un DataFrame de pandas.")
    if not isinstance(reporte_calidad, Mapping) or not isinstance(metadata, Mapping):
        raise TypeError("El reporte y la metadata deben ser diccionarios o mappings.")
    raiz = Path(raiz_proyecto).resolve(strict=True)
    if not raiz.is_dir():
        raise ValueError("La raíz del proyecto debe ser una carpeta existente.")
    paths = configuracion.get("paths", {})
    outputs = configuracion.get("outputs", {})
    silver = _resolver_carpeta(paths.get("silver_dir"), raiz, "paths.silver_dir")
    logs = _resolver_carpeta(paths.get("logs_dir"), raiz, "paths.logs_dir")
    protegidas = [
        _resolver_carpeta(paths.get("bronze_dir", "data/bronze"), raiz, "paths.bronze_dir"),
        _resolver_carpeta(paths.get("gold_dir", "data/gold"), raiz, "paths.gold_dir"),
    ]

    # Resolver todos los destinos antes de crear carpetas o escribir contenidos.
    destinos = {}
    for nombre, opcion in SALIDAS_TABLAS.items():
        archivo = _validar_nombre(outputs.get(opcion), ".parquet", opcion)
        destinos[nombre] = (silver / archivo).resolve()
    for nombre in ("reporte_calidad", "metadata_ejecucion"):
        opcion = "quality_report" if nombre == "reporte_calidad" else "execution_metadata"
        archivo = _validar_nombre(outputs.get(opcion), ".json", opcion)
        destinos[nombre] = (logs / archivo).resolve()

    # También se protegen entradas que la configuración sitúe fuera de Bronze.
    entradas = set()
    for fuente in configuracion.get("sources", {}).values():
        if isinstance(fuente, Mapping) and fuente.get("path"):
            entradas.add((raiz / fuente["path"]).resolve())
    normalizadas = [os.path.normcase(str(ruta)) for ruta in destinos.values()]
    if len(set(normalizadas)) != len(normalizadas):
        raise ValueError("Dos salidas apuntan al mismo archivo.")
    for destino in destinos.values():
        if not _esta_dentro(destino, raiz):
            raise ValueError(f"Una salida queda fuera del proyecto: {destino}")
        if any(_esta_dentro(destino, protegida) for protegida in protegidas):
            raise ValueError(f"Una salida intenta escribir en Bronze o Gold: {destino}")
        if destino in entradas:
            raise ValueError(f"Una salida coincide con un archivo de entrada: {destino}")
        if destino.exists() and not destino.is_file():
            raise ValueError(f"Una salida coincide con una carpeta: {destino}")
        if any(_esta_dentro(carpeta, destino) for carpeta in (silver, logs)):
            raise ValueError(f"Una salida coincide con una carpeta necesaria: {destino}")

    # Copiar la metadata antes de crear staging evita dejar carpetas si la copia falla.
    metadata_final = deepcopy(dict(metadata))
    # La carpeta temporal queda en el mismo proyecto y sistema de archivos.
    staging = Path(tempfile.mkdtemp(prefix=".silver_staging_", dir=str(raiz))).resolve()
    _validar_staging(staging, raiz)
    preparados = {}
    respaldos = {}
    publicados = []
    carpetas_creadas = []
    conservar_recuperacion = False
    try:
        LOGGER.info("Preparando las tablas Silver y sus reportes en staging.")
        reporte_temporal = staging / "reporte_calidad.json"
        _escribir_json(reporte_calidad, reporte_temporal)
        preparados["reporte_calidad"] = reporte_temporal
        salidas_metadata = {}
        for numero, nombre in enumerate(SALIDAS_TABLAS, start=1):
            tabla = tablas[nombre]
            temporal = staging / f"{numero:02d}_{nombre}.parquet"
            tabla.to_parquet(temporal, engine="pyarrow", index=False, compression="snappy")
            recuperada = pd.read_parquet(temporal, engine="pyarrow")
            pd.testing.assert_frame_equal(
                tabla.reset_index(drop=True), recuperada, check_exact=True, check_dtype=True
            )
            preparados[nombre] = temporal
            salidas_metadata[nombre] = {
                "archivo": str(destinos[nombre]),
                "filas": int(len(tabla)),
                "columnas": [
                    {"nombre": str(columna), "tipo": str(tipo)}
                    for columna, tipo in zip(tabla.columns, tabla.dtypes)
                ],
                "tamano_bytes": int(temporal.stat().st_size),
                "sha256": _huella_sha256(temporal),
            }
            LOGGER.info("Parquet %s verificado: %s filas.", nombre, len(tabla))
        metadata_final["salidas"] = salidas_metadata
        metadata_final["reporte_calidad"] = {
            "archivo": str(destinos["reporte_calidad"]),
            "tamano_bytes": int(reporte_temporal.stat().st_size),
            "sha256": _huella_sha256(reporte_temporal),
        }
        # Un JSON no puede contener su propia huella sin crear una dependencia circular.
        metadata_final["metadata_ejecucion"] = {
            "archivo": str(destinos["metadata_ejecucion"])
        }
        # Esta marca cierra la preparación/verificación; la publicación ocurre después.
        metadata_final["fin_exportacion_utc"] = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        metadata_temporal = staging / "metadata_ejecucion.json"
        _escribir_json(metadata_final, metadata_temporal)
        preparados["metadata_ejecucion"] = metadata_temporal

        # Guardar todas las versiones anteriores antes de reemplazar la primera salida.
        for carpeta in dict.fromkeys((silver, logs)):
            _crear_carpetas(carpeta, carpetas_creadas)
        for numero, (nombre, destino) in enumerate(destinos.items(), start=1):
            if destino.exists():
                respaldo = staging / f"respaldo_{numero:02d}"
                shutil.copy2(destino, respaldo)
                respaldos[nombre] = respaldo
        LOGGER.info("Publicando cuatro Parquet, el reporte y finalmente la metadata.")
        # El orden de destinos sitúa metadata_ejecucion después de las otras cinco salidas.
        for nombre, destino in destinos.items():
            preparados[nombre].replace(destino)
            publicados.append(nombre)
        LOGGER.info("Silver y reportes publicados correctamente.")
        return metadata_final
    except BaseException as error_publicacion:
        # Si alguna publicación falla, restaurar las salidas ya reemplazadas.
        fallos_recuperacion = []
        for nombre in reversed(publicados):
            destino = destinos[nombre]
            try:
                if nombre in respaldos:
                    respaldos[nombre].replace(destino)
                else:
                    destino.unlink()
            except OSError as error_recuperacion:
                fallos_recuperacion.append(f"{destino}: {error_recuperacion}")
        if fallos_recuperacion:
            # Conservar los respaldos es más seguro que borrarlos tras un fallo del sistema.
            conservar_recuperacion = True
            LOGGER.critical("No se pudo completar el rollback; respaldos en %s.", staging)
            raise RuntimeError(
                f"La publicación falló y requiere recuperación desde {staging}: "
                + "; ".join(fallos_recuperacion)
            ) from error_publicacion
        if publicados:
            LOGGER.warning("Publicación revertida; se restauraron las salidas anteriores.")
        for carpeta in reversed(carpetas_creadas):
            try:
                carpeta.rmdir()
            except OSError:
                # Una carpeta con otros archivos del usuario no se retira.
                pass
        raise
    finally:
        if not conservar_recuperacion:
            # Revalidar justo antes de borrar, por si la ruta cambió durante la ejecución.
            _validar_staging(staging, raiz)
            shutil.rmtree(staging)
