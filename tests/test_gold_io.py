"""Verificar lectura del panel y publicación completa de indicadores Gold.

Las pruebas escriben únicamente en raíces temporales y comprueban los archivos
reabiertos, sus huellas y la recuperación ante una publicación incompleta.
"""

import copy
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest
import yaml

from src.extract.read_integrated import leer_panel_integrado
from src.load import execution_metadata as trazabilidad
from src.load.export_gold import exportar_gold
from src.load.export_integration import exportar_integracion


@pytest.fixture
def configuracion():
    """Usar las rutas del proyecto con nombres independientes para los JSON Gold."""
    raiz = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))
    config["outputs"].setdefault("gold_quality_report", "reporte_indicadores.json")
    config["outputs"].setdefault("gold_metadata", "metadata_indicadores.json")
    return config


@pytest.fixture
def datos():
    """Incluir textos especiales, códigos, faltantes y un entero mayor de 2**53."""
    # El ejemplo comprueba persistencia, no calcula fórmulas. Int64 es esencial
    # para que el entero grande no pierda una unidad al convertirlo a float.
    return pd.DataFrame({
        "codigo_municipio": pd.Series(["05001", "05002"], dtype="string"),
        "anio": pd.Series([2024, 2024], dtype="Int64"),
        "municipio": pd.Series(["Medellín, norte", "NA"], dtype="string"),
        "poblacion_total": pd.Series([9007199254740993, pd.NA], dtype="Int64"),
        "accesos_t4": pd.Series([0, pd.NA], dtype="Int64"),
        "accesos_por_100_habitantes": pd.Series([0, pd.NA], dtype="Float64"),
        "porcentaje_centros_rural": pd.Series([25, pd.NA], dtype="Float64"),
        "crecimiento_anual_accesos": pd.Series([pd.NA, -100], dtype="Float64"),
        "accesos_por_100_habitantes_diagnostico": pd.Series([1 / 3, 5], dtype="Float64"),
        "estado_accesos_por_100_habitantes": pd.Series(["disponible", "no_calculable"], dtype="string"),
        "coincidencia_internet": pd.Series([True, False], dtype="boolean"),
    })


@pytest.fixture
def evidencia(datos, configuracion):
    """No presentar la aceptación del panel como consecuencia de escribir archivos."""
    metadata = {"ejecucion_id": "gold-prueba", "etapa": "indicadores", "estado": "exploratorio",
                "version_contrato": configuracion["project"]["data_contract"]["version"]}
    reporte = {**metadata, "filas_panel": len(datos),
               "aceptacion_panel": {"estado": "no_cumple", "cumple_meta": False}}
    return reporte, metadata


@pytest.fixture
def integrada(datos, configuracion, tmp_path):
    """Crear el panel de entrada y sus dos JSON mediante el exportador anterior."""
    raiz = tmp_path / "proyecto"
    raiz.mkdir()
    # Los originales protegidos permiten detectar sobrescrituras accidentales.
    for carpeta in ["bronze_dir", "silver_dir"]:
        destino = raiz / configuracion["paths"][carpeta]
        destino.mkdir(parents=True)
        (destino / "original_protegido.txt").write_text("Fuente intacta", encoding="utf-8")
    panel = datos[["codigo_municipio", "anio", "municipio", "poblacion_total", "accesos_t4"]].copy()
    etapa = {
        "ejecucion_id": "integracion-prueba", "etapa": "integracion", "estado": "exploratorio",
        "version_contrato": configuracion["project"]["data_contract"]["version"],
    }
    reporte = {**etapa, "filas_panel": len(panel),
               "aceptacion_panel": {"estado": "no_cumple", "cumple_meta": False}}
    metadata = {**etapa, "periodo": {
        "inicio": configuracion["processing"]["year_start"],
        "fin": configuracion["processing"]["year_end"],
    }}
    publicado = exportar_integracion(panel, reporte, metadata, configuracion, raiz)
    return raiz, panel, publicado


def _rutas_gold(raiz, configuracion):
    """Identificar los cuatro destinos que deben pertenecer a una misma ejecución."""
    gold = raiz / configuracion["paths"]["gold_dir"]
    logs = raiz / configuracion["paths"]["logs_dir"]
    return [gold / configuracion["outputs"]["indicators_gold"],
            gold / configuracion["outputs"]["indicators_gold_csv"],
            logs / configuracion["outputs"]["gold_quality_report"],
            logs / configuracion["outputs"]["gold_metadata"]]


def _contenido(raiz):
    """Capturar bytes finales para detectar cambios en fuentes y artefactos previos."""
    return {ruta.relative_to(raiz): ruta.read_bytes() for ruta in raiz.rglob("*") if ruta.is_file()}


def test_lector_integrado_preserva_panel_y_enlaza_aceptacion(configuracion, integrada):
    """La lectura recupera tipos y aceptación previa sin recalcular el ETL."""
    raiz, esperado, metadata = integrada
    panel, procedencia = leer_panel_integrado(configuracion, raiz)
    pd.testing.assert_frame_equal(panel, esperado, check_exact=True)
    assert procedencia["ejecucion_integracion"] == metadata["ejecucion_id"]
    assert procedencia["aceptacion_panel"] == {"estado": "no_cumple", "cumple_meta": False}
    assert set(procedencia["entradas_integracion"]) == {
        "panel_integrado", "reporte_integracion", "metadata_integracion",
    }
    for descripcion in procedencia["entradas_integracion"].values():
        archivo = Path(descripcion["archivo"])
        assert descripcion["sha256"] == hashlib.sha256(archivo.read_bytes()).hexdigest()
        assert descripcion["tamano_bytes"] == archivo.stat().st_size


@pytest.mark.parametrize("entrada", ["panel_integrado", "reporte_integracion"])
def test_lector_detecta_contenido_alterado_del_mismo_tamano(configuracion, integrada, entrada):
    """Una entrada diferente no debe aceptarse por conservar su tamaño."""
    raiz, _, metadata = integrada
    registro = metadata["salidas"][entrada] if entrada == "panel_integrado" else metadata[entrada]
    archivo = Path(registro["archivo"])
    anterior = archivo.read_bytes()
    archivo.write_bytes(anterior[:-1] + bytes([anterior[-1] ^ 1]))
    assert archivo.stat().st_size == len(anterior)
    with pytest.raises(ValueError):
        leer_panel_integrado(configuracion, raiz)


@pytest.mark.parametrize("entrada", ["panel_integrado", "reporte_integracion", "metadata_integracion"])
def test_lector_rechaza_entrada_ausente(configuracion, integrada, entrada):
    """El panel necesita sus tres archivos para acreditar procedencia."""
    raiz, _, metadata = integrada
    registro = metadata["salidas"][entrada] if entrada == "panel_integrado" else metadata[entrada]
    Path(registro["archivo"]).unlink()
    with pytest.raises(FileNotFoundError):
        leer_panel_integrado(configuracion, raiz)


@pytest.mark.parametrize("problema", ["ejecucion", "contrato", "periodo", "esquema"])
def test_lector_rechaza_manifiesto_de_otra_ejecucion_o_estructura(configuracion, integrada, problema):
    """La identidad y el esquema se comprueban además de la huella de los datos."""
    raiz, _, metadata = integrada
    alterada = copy.deepcopy(metadata)
    if problema == "ejecucion":
        alterada["ejecucion_id"] = "otra-integracion"
    elif problema == "contrato":
        alterada["version_contrato"] = "otra-version"
    elif problema == "periodo":
        alterada["periodo"]["inicio"] = 2017
    else:
        alterada["salidas"]["panel_integrado"]["columnas"][0]["tipo"] = "Int64"
    archivo = Path(metadata["metadata_integracion"]["archivo"])
    archivo.write_text(json.dumps(alterada, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        leer_panel_integrado(configuracion, raiz)


def test_lector_admite_proyecto_copiado_y_abre_rutas_actuales(configuracion, integrada, tmp_path):
    """Una copia íntegra puede conservar rutas históricas en el manifiesto."""
    raiz, esperado, _ = integrada
    copia = tmp_path / "copia_proyecto"
    shutil.copytree(raiz, copia)
    recuperado, procedencia = leer_panel_integrado(configuracion, copia)
    pd.testing.assert_frame_equal(recuperado, esperado, check_exact=True)
    for registro in procedencia["entradas_integracion"].values():
        assert copia.resolve() in Path(registro["archivo"]).parents


def test_gold_reabre_parquet_csv_y_verifica_tipos_faltantes_huellas(
        datos, configuracion, evidencia, integrada):
    """Comprobar artefactos reales, incluidos enteros que float no puede representar."""
    raiz, _, _ = integrada
    entradas_antes = _contenido(raiz)
    reporte, metadata = evidencia
    original = datos.copy(deep=True)
    reporte_original, metadata_original = copy.deepcopy(reporte), copy.deepcopy(metadata)
    resultado = exportar_gold(datos, reporte, metadata, configuracion, raiz)
    pd.testing.assert_frame_equal(datos, original, check_exact=True)
    assert reporte == reporte_original and metadata == metadata_original
    assert set(resultado["salidas"]) == {"indicadores_gold", "indicadores_gold_csv"}
    parquet = Path(resultado["salidas"]["indicadores_gold"]["archivo"])
    csv = Path(resultado["salidas"]["indicadores_gold_csv"]["archivo"])
    pd.testing.assert_frame_equal(pd.read_parquet(parquet), original, check_exact=True)
    # El consumidor de CSV debe declarar códigos como texto y campos anulables.
    opciones = configuracion["outputs"]["csv_options"]
    recuperada = pd.read_csv(csv, sep=opciones["sep"], encoding=opciones["encoding"],
                             dtype={columna: str(tipo) for columna, tipo in datos.dtypes.items()},
                             keep_default_na=False, na_values=[""])
    assert recuperada.loc[0, "codigo_municipio"] == "05001"
    assert recuperada.loc[1, "municipio"] == "NA"
    assert recuperada.loc[0, "poblacion_total"] == 9007199254740993
    assert pd.isna(recuperada.loc[1, "poblacion_total"])
    pd.testing.assert_frame_equal(recuperada, original, check_exact=False, rtol=1e-12, atol=1e-12)
    for registro in resultado["salidas"].values():
        archivo = Path(registro["archivo"])
        assert registro["filas"] == len(datos)
        assert registro["sha256"] == hashlib.sha256(archivo.read_bytes()).hexdigest()
        assert registro["tamano_bytes"] == archivo.stat().st_size
    assert json.loads(Path(resultado["reporte_indicadores"]["archivo"]).read_text(encoding="utf-8")) == reporte
    assert json.loads(Path(resultado["metadata_indicadores"]["archivo"]).read_text(encoding="utf-8")) == resultado
    # Las tres entradas integradas y las fuentes protegidas permanecen idénticas.
    for ruta, contenido in entradas_antes.items():
        assert (raiz / ruta).read_bytes() == contenido


@pytest.mark.parametrize("operacion", ["parquet", "csv", "verificacion"])
def test_fallo_previo_a_publicacion_no_deja_gold_parcial(
        datos, configuracion, evidencia, integrada, monkeypatch, operacion):
    """Preparar los cuatro artefactos antes de sustituir cualquiera de los finales."""
    raiz, _, _ = integrada
    anteriores = _contenido(raiz)

    def falla(*args, **kwargs):
        """Simular un fallo del almacenamiento sin tocar las entradas del usuario."""
        raise OSError("Fallo de almacenamiento Gold simulado")

    if operacion == "parquet":
        monkeypatch.setattr(pd.DataFrame, "to_parquet", falla)
    elif operacion == "csv":
        monkeypatch.setattr(pd.DataFrame, "to_csv", falla)
    else:
        monkeypatch.setattr(pd, "read_csv", falla)
    with pytest.raises(OSError):
        exportar_gold(datos, *evidencia, configuracion, raiz)
    assert _contenido(raiz) == anteriores
    assert not any(ruta.exists() for ruta in _rutas_gold(raiz, configuracion))


def test_fallo_de_publicacion_restaura_los_cuatro_archivos_previos(
        datos, configuracion, evidencia, integrada, monkeypatch):
    """No mezclar un Parquet nuevo con CSV y manifiestos de la ejecución anterior."""
    raiz, _, _ = integrada
    exportar_gold(datos, *evidencia, configuracion, raiz)
    anteriores = _contenido(raiz)
    objetivo = _rutas_gold(raiz, configuracion)[1].resolve()
    reemplazar_real = Path.replace
    fallos = []

    def reemplazar_con_fallo(origen, destino):
        """Fallar una vez después del primer reemplazo y permitir la restauración."""
        if Path(destino).resolve() == objetivo and not fallos:
            fallos.append(True)
            raise OSError("Fallo al publicar CSV Gold")
        return reemplazar_real(origen, destino)

    candidata = datos.copy(deep=True)
    candidata.loc[0, "porcentaje_centros_rural"] = 26
    metadata_nueva = copy.deepcopy(evidencia[1])
    metadata_nueva["ejecucion_id"] = "gold-segunda-prueba"
    monkeypatch.setattr(Path, "replace", reemplazar_con_fallo)
    with pytest.raises(OSError):
        exportar_gold(candidata, evidencia[0], metadata_nueva, configuracion, raiz)
    assert fallos
    assert _contenido(raiz) == anteriores


@pytest.mark.parametrize("problema", ["gold_bronze", "gold_silver", "gold_fuera", "logs_silver",
                                       "panel_integrado", "reporte_integrado", "metadata_integrada", "ruta_csv"])
def test_gold_rechaza_colisiones_y_ubicaciones_protegidas(
        datos, configuracion, evidencia, integrada, problema):
    """Los indicadores no pueden reemplazar sus entradas ni salir del proyecto."""
    raiz, _, _ = integrada
    anteriores = _contenido(raiz)
    reglas = copy.deepcopy(configuracion)
    if problema in {"gold_bronze", "gold_silver", "gold_fuera"}:
        reglas["paths"]["gold_dir"] = {
            "gold_bronze": reglas["paths"]["bronze_dir"],
            "gold_silver": reglas["paths"]["silver_dir"], "gold_fuera": "../fuera",
        }[problema]
    elif problema == "logs_silver":
        reglas["paths"]["logs_dir"] = reglas["paths"]["silver_dir"]
    elif problema == "panel_integrado":
        reglas["outputs"]["indicators_gold"] = reglas["outputs"]["integration_panel"]
    elif problema == "reporte_integrado":
        reglas["outputs"]["gold_quality_report"] = reglas["outputs"]["integration_quality_report"]
    elif problema == "metadata_integrada":
        reglas["outputs"]["gold_metadata"] = reglas["outputs"]["integration_metadata"]
    else:
        reglas["outputs"]["indicators_gold_csv"] = "../bronze/original.csv"
    with pytest.raises(ValueError):
        exportar_gold(datos, *evidencia, reglas, raiz)
    assert _contenido(raiz) == anteriores


def test_gold_json_no_finito_impide_publicacion(datos, configuracion, evidencia, integrada):
    """Un reporte con NaN debe fallar antes de anunciar artefactos completos."""
    raiz, _, _ = integrada
    anteriores = _contenido(raiz)
    evidencia[0]["valor_invalido"] = float("nan")
    with pytest.raises(ValueError):
        exportar_gold(datos, *evidencia, configuracion, raiz)
    assert _contenido(raiz) == anteriores


@pytest.fixture
def escenario_metadata(configuracion, integrada, monkeypatch):
    """Preparar código y configuración temporales junto al panel ya publicado."""
    raiz, _, _ = integrada
    ruta_config = raiz / "config" / "config.yaml"
    ruta_config.parent.mkdir()
    ruta_config.write_text(yaml.safe_dump(configuracion, allow_unicode=True), encoding="utf-8")
    (raiz / "main.py").write_text("# Coordinador original.\n", encoding="utf-8")
    codigo = raiz / "src" / "transform" / "build_indicators.py"
    codigo.parent.mkdir(parents=True)
    codigo.write_text("# Fórmulas originales.\n", encoding="utf-8")
    contrato = raiz / configuracion["project"]["data_contract"]["path"]
    contrato.parent.mkdir(parents=True)
    contrato.write_text("Contrato original.\n", encoding="utf-8")
    # Evitar procesos Git del computador: se prueba la integridad de archivos.
    monkeypatch.setattr(trazabilidad, "_estado_git", lambda raiz: {
        "commit_git": None, "cambios_locales": None,
    })
    _, procedencia = leer_panel_integrado(configuracion, raiz)
    return {
        "raiz": raiz, "configuracion": configuracion, "ruta_config": ruta_config,
        "codigo_fuente": codigo, "procedencia": procedencia,
        "huella_config": trazabilidad.huella_archivo(ruta_config),
        "codigo": trazabilidad.capturar_codigo(configuracion, raiz),
    }


def _alterar_entrada_gold(escenario, objetivo):
    """Modificar una entrada de la etapa, sin tocar archivos del proyecto real."""
    if objetivo == "configuracion":
        ruta = escenario["ruta_config"]
    elif objetivo == "codigo":
        ruta = escenario["codigo_fuente"]
    else:
        ruta = Path(escenario["procedencia"]["entradas_integracion"][objetivo]["archivo"])
    ruta.write_bytes(ruta.read_bytes() + b"\n# Cambio durante indicadores.\n")


def test_metadata_gold_conserva_aceptacion_previa_y_procedencia(escenario_metadata, monkeypatch):
    """Crear Gold no convierte un panel pendiente en un panel aprobado."""
    escenario = escenario_metadata

    def lectura_bronze(*args, **kwargs):
        """La metadata Gold usa las salidas integradas, sin releer Bronze."""
        pytest.fail("La metadata Gold intentó volver a las fuentes originales")

    monkeypatch.setattr(trazabilidad, "capturar_entradas", lectura_bronze)
    metadata = trazabilidad.crear_metadata_indicadores(
        escenario["configuracion"], escenario["raiz"], escenario["ruta_config"],
        "gold-prueba", "2026-10-06T12:00:00Z", escenario["procedencia"],
        escenario["huella_config"], escenario["codigo"],
    )
    assert metadata["etapa"] == "indicadores"
    assert metadata["estado"] == "exploratorio"
    assert metadata["integracion_verificada_sin_cambios"] is True
    assert metadata["procedencia"]["ejecucion_integracion"] == "integracion-prueba"
    assert metadata["procedencia"]["aceptacion_panel"] == {"estado": "no_cumple", "cumple_meta": False}


@pytest.mark.parametrize("objetivo", ["panel_integrado", "reporte_integracion",
                                       "metadata_integracion", "configuracion", "codigo"])
def test_metadata_gold_detecta_cambios_durante_el_calculo(escenario_metadata, objetivo):
    """No atribuir indicadores a archivos, configuración o código que cambiaron."""
    escenario = escenario_metadata
    _alterar_entrada_gold(escenario, objetivo)
    with pytest.raises(ValueError):
        trazabilidad.crear_metadata_indicadores(
            escenario["configuracion"], escenario["raiz"], escenario["ruta_config"],
            "gold-prueba", "2026-10-06T12:00:00Z", escenario["procedencia"],
            escenario["huella_config"], escenario["codigo"],
        )


@pytest.mark.parametrize("objetivo", ["panel_integrado", "metadata_integracion"])
def test_coordinador_gold_aborta_antes_de_publicar_entradas_modificadas(
        escenario_metadata, datos, monkeypatch, objetivo):
    """Confirmar la integridad después de calcular y antes de llamar al exportador."""
    import main as pipeline

    escenario = escenario_metadata
    publicaciones = []

    def construir_con_modificacion(*args, **kwargs):
        """Simular un cambio externo mientras se procesan las filas del panel."""
        _alterar_entrada_gold(escenario, objetivo)
        return datos.copy(deep=True), {"indicadores": {}}

    def publicar_sintetico(*args, **kwargs):
        """Detectar un intento de escribir Gold con procedencia inconsistente."""
        publicaciones.append(True)
        pytest.fail("Se intentó publicar Gold con entradas cambiadas")

    monkeypatch.setattr(pipeline, "RAIZ_PROYECTO", escenario["raiz"])
    monkeypatch.setattr(pipeline, "construir_indicadores", construir_con_modificacion)
    monkeypatch.setattr(pipeline, "exportar_gold", publicar_sintetico)
    with pytest.raises(ValueError):
        pipeline.ejecutar_gold(escenario["ruta_config"])
    assert not publicaciones
    assert not any(ruta.exists() for ruta in _rutas_gold(escenario["raiz"], escenario["configuracion"]))


def test_coordinador_gold_hereda_aceptacion_sin_declarar_aprobacion(
        escenario_metadata, datos, monkeypatch):
    """El coordinador debe copiar la aceptación de la integración verificada."""
    import main as pipeline

    escenario = escenario_metadata
    recibidos = []

    def construir_sintetico(*args, **kwargs):
        """Separar esta prueba del cálculo de fórmulas, ya comprobado en otro archivo."""
        return datos.copy(deep=True), {"indicadores": {}}

    def publicar_sintetico(datos_recibidos, reporte, metadata, config, raiz):
        """Examinar la evidencia que el coordinador entrega a la publicación."""
        assert reporte["aceptacion_panel"] == {"estado": "no_cumple", "cumple_meta": False}
        assert metadata["estado"] == "exploratorio"
        assert metadata["resumen_indicadores"]["aceptacion_panel"] == reporte["aceptacion_panel"]
        recibidos.append(metadata)
        return metadata

    monkeypatch.setattr(pipeline, "RAIZ_PROYECTO", escenario["raiz"])
    monkeypatch.setattr(pipeline, "construir_indicadores", construir_sintetico)
    monkeypatch.setattr(pipeline, "exportar_gold", publicar_sintetico)
    resultado = pipeline.ejecutar_gold(escenario["ruta_config"])
    assert resultado is recibidos[0]


def test_main_selecciona_gold_sin_repetir_etapas_anteriores(monkeypatch):
    """--gold consume el panel integrado y llama una sola vez al coordinador nuevo."""
    import main as pipeline

    resultado = {"ejecucion_id": "gold-sintetica"}
    llamadas = []

    def ejecutar_sintetico(ruta):
        """Simular el comando Gold sin utilizar archivos reales."""
        llamadas.append(("gold", ruta))
        return resultado

    def mostrar_sintetico(metadata):
        """La consola recibe exactamente la ejecución recién completada."""
        assert metadata is resultado
        llamadas.append(("mostrar", None))

    def etapa_anterior(*args, **kwargs):
        """Un selector incorrecto no debe volver a recorrer Bronze ni Silver."""
        pytest.fail("--gold intentó repetir una etapa anterior")

    monkeypatch.setattr(pipeline, "ejecutar_gold", ejecutar_sintetico)
    monkeypatch.setattr(pipeline, "_mostrar_gold", mostrar_sintetico)
    for nombre in ["ejecutar_integracion", "ejecutar_silver", "ejecutar_educacion",
                   "ejecutar_poblacion", "ejecutar_internet", "ejecutar_divipola"]:
        monkeypatch.setattr(pipeline, nombre, etapa_anterior)
    monkeypatch.setattr("sys.argv", ["main.py", "--gold"])
    pipeline.main()
    assert llamadas == [("gold", None), ("mostrar", None)]


@pytest.mark.parametrize("otros", [["--silver"], ["--integrar"], ["--fuente", "internet"]])
def test_main_rechaza_gold_junto_con_otro_modo(monkeypatch, otros):
    """Evitar que una misma ejecución combine modos incompatibles."""
    import main as pipeline

    monkeypatch.setattr("sys.argv", ["main.py", "--gold"] + otros)
    with pytest.raises(SystemExit) as error:
        pipeline.main()
    assert error.value.code == 2
