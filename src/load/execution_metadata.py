"""Registrar las entradas y el codigo utilizados, con integridad y fechas reales."""

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


FUENTES = {"educacion": "education_stats", "poblacion": "population",
           "internet": "internet_access", "divipola": "divipola"}


def huella_archivo(ruta: Path) -> str:
    """Calcular SHA-256 leyendo bytes por bloques, sin cargar toda la fuente."""
    resultado = hashlib.sha256()
    with Path(ruta).open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resultado.update(bloque)
    return resultado.hexdigest()


def capturar_entradas(configuracion: Mapping, raiz_proyecto: Path) -> Dict[str, Any]:
    """Capturar integridad; la fecha del archivo no es su fecha de descarga."""
    entradas = {}
    for nombre, clave in FUENTES.items():
        ruta = Path(configuracion["sources"][clave]["path"])
        ruta = (raiz_proyecto / ruta).resolve() if not ruta.is_absolute() else ruta.resolve()
        estado = ruta.stat()
        entradas[nombre] = {
            "archivo": str(ruta), "tamano_bytes": estado.st_size,
            "sha256": huella_archivo(ruta),
            "modificado_archivo_utc": datetime.fromtimestamp(estado.st_mtime, timezone.utc).isoformat(),
            "fecha_descarga": None, "version_fuente": None,
        }
    return entradas


def _estado_git(raiz: Path) -> Dict[str, Any]:
    """Leer Git local si existe, sin red ni modificar su configuracion."""
    base = ["git", "-c", "safe.directory=" + str(raiz), "-C", str(raiz)]
    try:
        revision = subprocess.run(base + ["rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        cambios = subprocess.run(base + ["status", "--porcelain"], capture_output=True, text=True, timeout=10)
        return {
            "commit_git": revision.stdout.strip() if revision.returncode == 0 else None,
            "cambios_locales": bool(cambios.stdout.strip()) if cambios.returncode == 0 else None,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"commit_git": None, "cambios_locales": None}


def crear_metadata_silver(
    configuracion: Mapping, raiz_proyecto: Path, ruta_configuracion: Path,
    ejecucion_id: str, inicio_utc: str, entradas_antes: Dict[str, Any],
    huella_configuracion: Optional[str] = None,
) -> Dict[str, Any]:
    """Verificar Bronze tras E/T y describir la preparacion sin inventar fechas."""
    entradas = capturar_entradas(configuracion, raiz_proyecto)
    huella_actual_config = huella_archivo(ruta_configuracion)
    if huella_configuracion is not None and huella_actual_config != huella_configuracion:
        raise ValueError("La configuracion cambio durante la preparacion; no se publica Silver.")
    for nombre in FUENTES:
        if (entradas[nombre]["sha256"] != entradas_antes[nombre]["sha256"]
                or entradas[nombre]["tamano_bytes"] != entradas_antes[nombre]["tamano_bytes"]):
            raise ValueError("La fuente {} cambio durante la preparacion; no se publica Silver.".format(nombre))
    codigo = _estado_git(raiz_proyecto)
    archivos = [raiz_proyecto / "main.py"] + sorted((raiz_proyecto / "src").rglob("*.py"))
    contrato = raiz_proyecto / configuracion["project"]["data_contract"]["path"]
    if contrato.is_file():
        archivos.append(contrato)
    # Una copia con cambios locales queda identificada por sus hashes de codigo.
    codigo["archivos"] = [{"archivo": str(ruta.resolve()), "sha256": huella_archivo(ruta)}
                         for ruta in archivos if ruta.is_file()]
    return {
        "ejecucion_id": ejecucion_id, "etapa": "silver", "estado": "exploratorio",
        "inicio_utc": inicio_utc,
        "fin_preparacion_utc": datetime.now(timezone.utc).isoformat(),
        "version_proyecto": configuracion["project"]["version"],
        "version_contrato": configuracion["project"]["data_contract"]["version"],
        "periodo": {"inicio": configuracion["processing"]["year_start"], "fin": configuracion["processing"]["year_end"]},
        "trimestre_referencia": configuracion["processing"]["internet_quarter"],
        "entradas": entradas, "bronze_verificado_sin_cambios": True,
        "configuracion": {"archivo": str(ruta_configuracion.resolve()), "sha256": huella_actual_config},
        "codigo": codigo,
    }
