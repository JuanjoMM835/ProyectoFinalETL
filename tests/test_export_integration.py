"""Probar la publicación del panel exploratorio sin tocar las fuentes reales.

Las raíces temporales permiten simular fallos del disco y comprobar que una
publicación incompleta no mezcla Parquet nuevos con reportes anteriores.
"""

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.load.export_integration import exportar_integracion


@pytest.fixture
def configuracion():
    """Definir rutas de prueba independientes del YAML y de las salidas reales."""
    return {
        "paths": {"bronze_dir": "data/bronze", "silver_dir": "data/silver",
                  "gold_dir": "data/gold", "logs_dir": "logs"},
        "sources": {"educacion": {"path": "data/bronze/entrada.csv"}},
        "outputs": {
            "integration_panel": "panel_integrado_exploratorio.parquet",
            "integration_quality_report": "reporte_integracion.json",
            "integration_metadata": "metadata_integracion.json",
            "quality_report": "reporte_calidad.json",
            "execution_metadata": "metadata_ejecucion.json",
            "indicators_gold": "indicadores_municipio_anio.parquet",
            "indicators_gold_csv": "indicadores_municipio_anio.csv",
        },
    }


@pytest.fixture
def panel():
    """Combinar ceros y faltantes con los tipos anulables prometidos en el panel."""
    return pd.DataFrame({
        "codigo_municipio": pd.Series(["05001", "05002"], dtype="string"),
        "anio": pd.Series([2024, 2024], dtype="Int64"),
        "poblacion_total": pd.Series([100, pd.NA], dtype="Int64"),
        "poblacion_centros_rural": pd.Series([20, pd.NA], dtype="Int64"),
        "accesos_t4": pd.Series([0, pd.NA], dtype="Int64"),
        "cobertura_neta": pd.Series([80, pd.NA], dtype="Float64"),
        "desercion": pd.Series([0, pd.NA], dtype="Float64"),
        "reprobacion": pd.Series([1.5, pd.NA], dtype="Float64"),
        "estado_homologacion": pd.Series(["pendiente_revision"] * 2, dtype="string"),
        "coincidencia_internet": pd.Series([True, False], dtype="boolean"),
    })


@pytest.fixture
def reporte():
    """Conservar el estado exploratorio y un faltante que JSON debe representar con null."""
    return {"ejecucion_id": "integracion-prueba", "etapa": "integracion",
            "estado": "exploratorio", "observacion": "Revisión territorial pendiente",
            "evidencia_temporal": None,
            "aceptacion_panel": {"estado": "no_cumple", "cumple_meta": False}}


@pytest.fixture
def raiz_y_protegidos(tmp_path, configuracion):
    """Crear otras etapas ficticias para comprobar que la publicación las conserva."""
    archivos = {
        "data/bronze/entrada.csv": b"original Bronze",
        "data/silver/educacion_limpia.parquet": b"original Silver",
        "logs/reporte_calidad.json": b'{"etapa":"silver"}',
        "logs/metadata_ejecucion.json": b'{"ejecucion_id":"silver-original"}',
        "data/gold/indicadores_municipio_anio.parquet": b"indicadores previos",
        "data/gold/indicadores_municipio_anio.csv": b"indicador,valor\nprueba,1\n",
        "config/config.yaml": b"version: 1\n",
    }
    protegidos = {}
    for relativo, contenido in archivos.items():
        ruta = tmp_path / relativo
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido)
        protegidos[ruta] = contenido
    return tmp_path, protegidos


def _metadata(raiz):
    """Registrar una configuración real de prueba, sin hashes de fuentes del proyecto."""
    return {"ejecucion_id": "integracion-prueba", "etapa": "integracion",
            "estado": "exploratorio", "detalle": {"version": 1},
            "configuracion": {"archivo": str(raiz / "config/config.yaml")}}


def _destinos(raiz, configuracion):
    """Enumerar exclusivamente los tres archivos que esta operación puede publicar."""
    paths, outputs = configuracion["paths"], configuracion["outputs"]
    return {
        "panel": (raiz / paths["gold_dir"] / outputs["integration_panel"]).resolve(),
        "reporte": (raiz / paths["logs_dir"] / outputs["integration_quality_report"]).resolve(),
        "metadata": (raiz / paths["logs_dir"] / outputs["integration_metadata"]).resolve(),
    }


def _comprobar_protegidos(protegidos):
    """Exigir preservación byte a byte de las etapas e inputs que no se actualizan."""
    for ruta, contenido in protegidos.items():
        assert ruta.read_bytes() == contenido


def test_publica_tres_archivos_con_huellas_y_preserva_entradas(
        configuracion, panel, reporte, raiz_y_protegidos):
    """Verificar el producto completo, sus JSON y su trazabilidad tras la escritura."""
    raiz, protegidos = raiz_y_protegidos
    metadata = _metadata(raiz)
    originales = panel.copy(deep=True), copy.deepcopy(reporte), copy.deepcopy(metadata)
    existentes = {ruta for ruta in raiz.rglob("*") if ruta.is_file()}
    resultado = exportar_integracion(panel, reporte, metadata, configuracion, raiz)
    destinos = _destinos(raiz, configuracion)
    actuales = {ruta for ruta in raiz.rglob("*") if ruta.is_file()}
    assert actuales - existentes == set(destinos.values())
    assert set(resultado["salidas"]) == {"panel_integrado"}
    salida = resultado["salidas"]["panel_integrado"]
    assert salida["archivo"] == str(destinos["panel"])
    assert salida["filas"] == len(panel)
    assert salida["columnas"] == [{"nombre": col, "tipo": str(tipo)}
                                  for col, tipo in panel.dtypes.items()]
    for descripcion, archivo in ((salida, destinos["panel"]),
                                 (resultado["reporte_integracion"], destinos["reporte"])):
        assert descripcion["sha256"] == hashlib.sha256(archivo.read_bytes()).hexdigest()
        assert descripcion["tamano_bytes"] == archivo.stat().st_size
    assert resultado["reporte_integracion"]["archivo"] == str(destinos["reporte"])
    assert resultado["metadata_integracion"]["archivo"] == str(destinos["metadata"])
    assert json.loads(destinos["reporte"].read_text(encoding="utf-8")) == reporte
    assert json.loads(destinos["metadata"].read_text(encoding="utf-8")) == resultado
    fecha = datetime.fromisoformat(resultado["fin_exportacion_utc"].replace("Z", "+00:00"))
    assert fecha.utcoffset() == timezone.utc.utcoffset(fecha)
    pd.testing.assert_frame_equal(pd.read_parquet(destinos["panel"]), panel, check_exact=True)
    pd.testing.assert_frame_equal(panel, originales[0], check_exact=True)
    assert reporte == originales[1] and metadata == originales[2]
    _comprobar_protegidos(protegidos)
    assert not list(raiz.glob(".integration_staging_*"))


def test_roundtrip_preserva_tipos_faltantes_y_descarta_solo_indice_tecnico(
        configuracion, panel, reporte, raiz_y_protegidos):
    """El código 05001 y el cero observado sobreviven, aunque el índice no se exporte."""
    raiz, _ = raiz_y_protegidos
    panel.index = pd.Index([10, 20], name="indice_tecnico")
    original = panel.copy(deep=True)
    resultado = exportar_integracion(panel, reporte, _metadata(raiz), configuracion, raiz)
    recuperado = pd.read_parquet(resultado["salidas"]["panel_integrado"]["archivo"])
    pd.testing.assert_frame_equal(recuperado, original.reset_index(drop=True), check_exact=True)
    pd.testing.assert_frame_equal(panel, original, check_exact=True)
    assert recuperado.loc[0, "codigo_municipio"] == "05001"
    assert recuperado.loc[0, "accesos_t4"] == 0
    assert pd.isna(recuperado.loc[1, "accesos_t4"])


@pytest.mark.parametrize("con_version_anterior", [False, True])
@pytest.mark.parametrize("objetivo", ["reporte", "metadata"])
def test_fallo_de_reemplazo_restaura_version_anterior_o_retira_salidas_nuevas(
        configuracion, panel, reporte, raiz_y_protegidos, monkeypatch,
        con_version_anterior, objetivo):
    """No dejar un panel nuevo acompañado por la metadata de otra ejecución."""
    raiz, protegidos = raiz_y_protegidos
    metadata = _metadata(raiz)
    destinos = _destinos(raiz, configuracion)
    if con_version_anterior:
        exportar_integracion(panel, reporte, metadata, configuracion, raiz)
    previos = {ruta: ruta.read_bytes() for ruta in destinos.values() if ruta.exists()}
    reemplazar_real, fallos = Path.replace, []

    def reemplazar_con_fallo(origen, destino):
        """Fallar una sola publicación y permitir la restauración posterior del respaldo."""
        if Path(destino).resolve() == destinos[objetivo] and not fallos:
            fallos.append(True)
            raise OSError("Fallo de publicación simulado")
        return reemplazar_real(origen, destino)

    candidato = panel.copy(deep=True)
    candidato.loc[0, "cobertura_neta"] = 81
    nueva_metadata = copy.deepcopy(metadata)
    nueva_metadata["ejecucion_id"] = "integracion-segunda"
    monkeypatch.setattr(Path, "replace", reemplazar_con_fallo)
    with pytest.raises(OSError):
        exportar_integracion(candidato, reporte, nueva_metadata, configuracion, raiz)
    assert fallos
    for ruta in destinos.values():
        if ruta in previos:
            assert ruta.read_bytes() == previos[ruta]
        else:
            assert not ruta.exists()
    _comprobar_protegidos(protegidos)
    assert not list(raiz.glob(".integration_staging_*"))


@pytest.mark.parametrize("fallo", ["escritura", "lectura", "tipos"])
def test_fallo_antes_de_publicacion_conserva_los_tres_archivos_previos(
        configuracion, panel, reporte, raiz_y_protegidos, monkeypatch, fallo):
    """Una falla de disco o un tipo alterado impide reemplazar cualquier salida."""
    raiz, protegidos = raiz_y_protegidos
    exportar_integracion(panel, reporte, _metadata(raiz), configuracion, raiz)
    anteriores = {ruta: ruta.read_bytes() for ruta in _destinos(raiz, configuracion).values()}
    leer_real = pd.read_parquet

    def fallar(*args, **kwargs):
        """Representar una falla de almacenamiento reproducible."""
        raise OSError("Fallo previo a publicación")

    def leer_con_tipo_alterado(*args, **kwargs):
        """Simular un Parquet legible que perdió el tipo string del código territorial."""
        resultado = leer_real(*args, **kwargs)
        resultado["codigo_municipio"] = resultado["codigo_municipio"].astype("object")
        return resultado

    if fallo == "escritura":
        monkeypatch.setattr(pd.DataFrame, "to_parquet", fallar)
    else:
        monkeypatch.setattr(pd, "read_parquet", leer_con_tipo_alterado if fallo == "tipos" else fallar)
    with pytest.raises(AssertionError if fallo == "tipos" else OSError):
        exportar_integracion(panel, reporte, _metadata(raiz), configuracion, raiz)
    for ruta, contenido in anteriores.items():
        assert ruta.read_bytes() == contenido
    _comprobar_protegidos(protegidos)
    assert not list(raiz.glob(".integration_staging_*"))


@pytest.mark.parametrize("destino", ["reporte", "metadata"])
def test_json_no_finito_impide_publicar(configuracion, panel, reporte, raiz_y_protegidos, destino):
    """El JSON rechazado no debe acompañar un Parquet nuevo aparentemente exitoso."""
    raiz, protegidos = raiz_y_protegidos
    metadata = _metadata(raiz)
    (reporte if destino == "reporte" else metadata)["no_finito"] = float("nan")
    with pytest.raises(ValueError):
        exportar_integracion(panel, reporte, metadata, configuracion, raiz)
    assert not any(ruta.exists() for ruta in _destinos(raiz, configuracion).values())
    _comprobar_protegidos(protegidos)
    assert not list(raiz.glob(".integration_staging_*"))


@pytest.mark.parametrize("problema", [
    "gold_silver", "gold_bronze", "logs_silver", "logs_bronze", "gold_fuera", "logs_fuera",
    "reporte_silver", "metadata_silver", "json_repetido", "nombre_con_ruta", "indicadores", "entrada",
])
def test_rechaza_rutas_protegidas_y_colisiones_antes_de_publicar(
        configuracion, panel, reporte, raiz_y_protegidos, problema):
    """Una configuración equivocada no puede destruir fuentes ni productos de otra etapa."""
    raiz, protegidos = raiz_y_protegidos
    reglas = copy.deepcopy(configuracion)
    if problema.startswith(("gold_", "logs_")):
        carpeta, caso = problema.split("_", 1)
        reglas["paths"][carpeta + "_dir"] = "../fuera" if caso == "fuera" else reglas["paths"][caso + "_dir"]
    elif problema == "reporte_silver":
        reglas["outputs"]["integration_quality_report"] = reglas["outputs"]["quality_report"]
    elif problema == "metadata_silver":
        reglas["outputs"]["integration_metadata"] = reglas["outputs"]["execution_metadata"]
    elif problema == "json_repetido":
        reglas["outputs"]["integration_metadata"] = reglas["outputs"]["integration_quality_report"]
    elif problema == "nombre_con_ruta":
        reglas["outputs"]["integration_panel"] = "../silver/panel.parquet"
    elif problema == "indicadores":
        reglas["outputs"]["integration_panel"] = reglas["outputs"]["indicators_gold"]
    else:
        reglas["sources"]["educacion"]["path"] = str(_destinos(raiz, reglas)["panel"])
    with pytest.raises(ValueError):
        exportar_integracion(panel, reporte, _metadata(raiz), reglas, raiz)
    assert not any(ruta.exists() for ruta in _destinos(raiz, configuracion).values())
    _comprobar_protegidos(protegidos)
    assert not list(raiz.glob(".integration_staging_*"))
