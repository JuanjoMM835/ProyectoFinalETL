"""Proteger la procedencia del panel si una entrada cambia durante su cruce.

Todos los archivos pertenecen a carpetas temporales de prueba. La metadata de
integración se construye con Silver y nunca necesita abrir fuentes Bronze.
"""

import copy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.load import execution_metadata as trazabilidad


@pytest.fixture
def escenario(tmp_path, monkeypatch):
    """Crear seis entradas y tres archivos de código pequeños con huellas reales."""
    raiz_real = Path(__file__).resolve().parents[1]
    configuracion = yaml.safe_load(
        (raiz_real / "config" / "config.yaml").read_text(encoding="utf-8")
    )
    # Aislar los seis archivos Silver sintéticos de los catálogos territoriales
    # reales, cuya verificación pertenece a las pruebas de evidencia temporal.
    configuracion.setdefault("territorial_evidence", {})["enabled"] = False
    raiz = tmp_path / "proyecto"
    raiz.mkdir()
    ruta_config = raiz / "config" / "config.yaml"
    ruta_config.parent.mkdir()
    ruta_config.write_text(yaml.safe_dump(configuracion, allow_unicode=True), encoding="utf-8")
    codigo_fuente = raiz / "src" / "transform" / "integrate_sources.py"
    codigo_fuente.parent.mkdir(parents=True)
    codigo_fuente.write_text("# Código original de prueba.\n", encoding="utf-8")
    (raiz / "main.py").write_text("# Coordinador original.\n", encoding="utf-8")
    contrato = raiz / configuracion["project"]["data_contract"]["path"]
    contrato.parent.mkdir(parents=True)
    contrato.write_text("Contrato original de prueba.\n", encoding="utf-8")

    # Evitamos consultar el Git del computador: aquí comprobamos las huellas
    # de archivos, que también identifican código con cambios sin commit.
    monkeypatch.setattr(trazabilidad, "_estado_git", lambda raiz: {
        "commit_git": None, "cambios_locales": None,
    })
    entradas = {}
    for fuente in ["educacion", "poblacion", "internet", "divipola"]:
        archivo = raiz / "data" / "silver" / (fuente + ".parquet")
        archivo.parent.mkdir(parents=True, exist_ok=True)
        # Esta prueba de integridad trabaja con bytes; no pretende leer Parquet.
        archivo.write_bytes(("original " + fuente).encode("utf-8"))
        entradas[fuente] = {
            "archivo_actual": str(archivo), "tamano_bytes": archivo.stat().st_size,
            "sha256": trazabilidad.huella_archivo(archivo),
        }
    evidencia = {}
    for nombre in ["metadata_silver", "reporte_calidad_silver"]:
        archivo = raiz / "logs" / (nombre + ".json")
        archivo.parent.mkdir(parents=True, exist_ok=True)
        archivo.write_text('{"original": true}\n', encoding="utf-8")
        evidencia[nombre] = {"archivo": str(archivo), "sha256": trazabilidad.huella_archivo(archivo)}
    procedencia = {
        "ejecucion_silver": "silver-sintetica", "entradas_silver": entradas,
        "catalogo_temporal": {"vigencia_historica_verificada": False}, **evidencia,
    }
    return {
        "raiz": raiz, "configuracion": configuracion, "ruta_config": ruta_config,
        "huella_config": trazabilidad.huella_archivo(ruta_config),
        "codigo": trazabilidad.capturar_codigo(configuracion, raiz),
        "codigo_fuente": codigo_fuente, "procedencia": procedencia,
    }


def _crear_metadata(escenario):
    """Invocar la API con las huellas capturadas antes de iniciar el cruce."""
    return trazabilidad.crear_metadata_integracion(
        escenario["configuracion"], escenario["raiz"], escenario["ruta_config"],
        "integracion-sintetica", "2026-10-06T12:00:00Z",
        escenario["procedencia"], escenario["huella_config"], escenario["codigo"],
    )


def _alterar(escenario, objetivo):
    """Cambiar contenido manteniendo el tamaño cuando se prueba una entrada."""
    if objetivo in escenario["procedencia"]["entradas_silver"]:
        ruta = Path(escenario["procedencia"]["entradas_silver"][objetivo]["archivo_actual"])
    elif objetivo in {"metadata_silver", "reporte_calidad_silver"}:
        ruta = Path(escenario["procedencia"][objetivo]["archivo"])
    elif objetivo == "configuracion":
        ruta = escenario["ruta_config"]
    else:
        ruta = escenario["codigo_fuente"]
    if objetivo in {"configuracion", "codigo"}:
        ruta.write_bytes(ruta.read_bytes() + b"\n# Cambio durante el cruce.\n")
    else:
        anteriores = ruta.read_bytes()
        ruta.write_bytes(anteriores.replace(b"original", b"alterada"))
        assert ruta.stat().st_size == len(anteriores)


def test_metadata_enlaza_silver_sin_necesitar_bronze(escenario, monkeypatch):
    """Registrar la ejecución anterior y las seis huellas sin releer originales."""
    originales = copy.deepcopy(escenario["procedencia"])

    def lectura_bronze(*args, **kwargs):
        """Impedir que una implementación futura vuelva a leer Bronze aquí."""
        pytest.fail("La metadata de integración intentó releer Bronze")

    monkeypatch.setattr(trazabilidad, "capturar_entradas", lectura_bronze)
    assert not (escenario["raiz"] / "data" / "bronze").exists()
    metadata = _crear_metadata(escenario)
    assert metadata["etapa"] == "integracion"
    assert metadata["estado"] == "exploratorio"
    assert metadata["silver_verificado_sin_cambios"] is True
    assert metadata["procedencia"]["ejecucion_silver"] == "silver-sintetica"
    assert set(metadata["procedencia"]["entradas_silver"]) == {
        "educacion", "poblacion", "internet", "divipola",
    }
    assert metadata["configuracion"]["sha256"] == escenario["huella_config"]
    assert escenario["procedencia"] == originales
    assert len(metadata["codigo"]["archivos"]) == 3


@pytest.mark.parametrize("objetivo", [
    "educacion", "poblacion", "internet", "divipola",
    "metadata_silver", "reporte_calidad_silver", "configuracion", "codigo",
])
def test_metadata_detecta_cambios_durante_integracion(escenario, objetivo):
    """Un cruce no puede atribuirse a entradas, reglas o código ya modificados."""
    _alterar(escenario, objetivo)
    with pytest.raises(ValueError):
        _crear_metadata(escenario)


@pytest.mark.parametrize("objetivo", ["poblacion", "metadata_silver", "configuracion", "codigo"])
def test_coordinador_aborta_publicacion_si_cambia_una_entrada(
        escenario, monkeypatch, objetivo):
    """La revalidación debe ocurrir antes de entregar el panel al exportador."""
    import main as pipeline

    publicaciones = []

    def leer_sintetico(configuracion, raiz):
        """Representar archivos verificados por el lector al comienzo del cruce."""
        assert raiz == escenario["raiz"]
        return {}, escenario["procedencia"]

    def cruce_con_modificacion(*args, **kwargs):
        """Simular otro proceso modificando un archivo mientras se hacen las uniones."""
        _alterar(escenario, objetivo)
        return pd.DataFrame(), {}

    def publicar_sintetico(*args, **kwargs):
        """Registrar cualquier intento de publicar una ejecución inconsistente."""
        publicaciones.append(True)
        pytest.fail("Se intentó publicar un panel con entradas modificadas")

    monkeypatch.setattr(pipeline, "RAIZ_PROYECTO", escenario["raiz"])
    monkeypatch.setattr(pipeline, "leer_silver", leer_sintetico)
    monkeypatch.setattr(pipeline, "integrar_fuentes", cruce_con_modificacion)
    monkeypatch.setattr(pipeline, "exportar_integracion", publicar_sintetico)
    with pytest.raises(ValueError):
        pipeline.ejecutar_integracion(escenario["ruta_config"])
    assert not publicaciones
    assert not (escenario["raiz"] / escenario["configuracion"]["paths"]["gold_dir"]).exists()
