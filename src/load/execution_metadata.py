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


def capturar_codigo(configuracion: Mapping, raiz: Path) -> Dict[str, Any]:
    """Identificar el codigo y el contrato antes de comenzar la integracion."""
    codigo = _estado_git(raiz)
    archivos = [raiz / "main.py"] + sorted((raiz / "src").rglob("*.py"))
    archivos.append(raiz / configuracion["project"]["data_contract"]["path"])
    # Los hashes describen tambien cambios locales que aun no tienen un commit.
    codigo["archivos"] = [{"archivo": str(ruta.resolve()), "sha256": huella_archivo(ruta)}
                         for ruta in archivos if ruta.is_file()]
    return codigo


def crear_metadata_integracion(
    configuracion: Mapping, raiz: Path, ruta_configuracion: Path,
    ejecucion_id: str, inicio_utc: str, procedencia: dict,
    huella_configuracion: str, codigo: dict,
) -> Dict[str, Any]:
    """Confirmar entradas Silver y describir esta ejecucion, sin releer Bronze."""
    if huella_archivo(ruta_configuracion) != huella_configuracion:
        raise ValueError("La configuracion cambio durante la integracion; no se publica el panel.")
    # Confirmamos los seis archivos consumidos: cuatro tablas y sus dos JSON.
    # El lector ya verifico filas y tipos; aqui detectamos cambios durante el cruce.
    for entrada in procedencia["entradas_silver"].values():
        ruta = Path(entrada["archivo_actual"])
        if ruta.stat().st_size != entrada["tamano_bytes"] or huella_archivo(ruta) != entrada["sha256"]:
            raise ValueError("Una tabla Silver cambio durante la integracion: {}".format(ruta.name))
    for opcion in ("metadata_silver", "reporte_calidad_silver"):
        entrada = procedencia[opcion]
        if huella_archivo(Path(entrada["archivo"])) != entrada["sha256"]:
            raise ValueError("La evidencia Silver cambio durante la integracion.")
    # Las referencias temporales son entradas de esta etapa cuando se usan.
    for entrada in procedencia.get("entradas_referencia", []):
        ruta = Path(entrada["archivo"])
        if ruta.stat().st_size != entrada["tamano_bytes"] or huella_archivo(ruta) != entrada["sha256"]:
            raise ValueError("La evidencia territorial cambio durante la integracion.")
    for archivo in codigo["archivos"]:
        if huella_archivo(Path(archivo["archivo"])) != archivo["sha256"]:
            raise ValueError("El codigo o contrato cambio durante la integracion.")
    return {
        "ejecucion_id": ejecucion_id, "etapa": "integracion", "estado": "exploratorio",
        "inicio_utc": inicio_utc, "fin_preparacion_utc": datetime.now(timezone.utc).isoformat(),
        "version_proyecto": configuracion["project"]["version"],
        "version_contrato": configuracion["project"]["data_contract"]["version"],
        "periodo": {"inicio": configuracion["processing"]["year_start"],
                    "fin": configuracion["processing"]["year_end"]},
        "trimestre_referencia": configuracion["processing"]["internet_quarter"],
        "procedencia": procedencia, "silver_verificado_sin_cambios": True,
        "configuracion": {"archivo": str(ruta_configuracion), "sha256": huella_configuracion},
        "codigo": codigo,
    }


def crear_metadata_indicadores(
    configuracion: Mapping, raiz: Path, ruta_configuracion: Path,
    ejecucion_id: str, inicio_utc: str, procedencia: dict,
    huella_configuracion: str, codigo: dict,
) -> Dict[str, Any]:
    """Describir Gold y confirmar que el panel y sus evidencias no cambiaron."""
    if huella_archivo(ruta_configuracion) != huella_configuracion:
        raise ValueError("La configuracion cambio durante el calculo; no se publica Gold.")
    for entrada in procedencia["entradas_integracion"].values():
        ruta = Path(entrada["archivo"])
        if ruta.stat().st_size != entrada["tamano_bytes"] or huella_archivo(ruta) != entrada["sha256"]:
            raise ValueError("Una entrada integrada cambio durante el calculo de indicadores.")
    for archivo in codigo["archivos"]:
        if huella_archivo(Path(archivo["archivo"])) != archivo["sha256"]:
            raise ValueError("El codigo o contrato cambio durante el calculo de indicadores.")
    return {
        "ejecucion_id": ejecucion_id, "etapa": "indicadores", "estado": "exploratorio",
        "inicio_utc": inicio_utc, "fin_preparacion_utc": datetime.now(timezone.utc).isoformat(),
        "version_proyecto": configuracion["project"]["version"],
        "version_contrato": configuracion["project"]["data_contract"]["version"],
        "periodo": {"inicio": configuracion["processing"]["year_start"],
                    "fin": configuracion["processing"]["year_end"]},
        "trimestre_referencia": configuracion["processing"]["internet_quarter"],
        "procedencia": procedencia, "integracion_verificada_sin_cambios": True,
        "configuracion": {"archivo": str(ruta_configuracion), "sha256": huella_configuracion},
        "codigo": codigo,
    }
