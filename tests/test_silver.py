"""Pruebas de calidad exploratoria y publicacion completa de las cuatro tablas Silver."""

import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.load.export_results import exportar_silver
from src.load.execution_metadata import capturar_entradas, crear_metadata_silver
from src.transform.quality_silver import construir_reporte_silver


NOMBRES_SILVER = {
    "educacion": "education_silver", "poblacion": "population_silver",
    "internet": "internet_silver", "divipola": "divipola_silver",
}


@pytest.fixture
def configuracion():
    """Leer una configuracion independiente sin alterar el YAML del proyecto."""
    raiz = Path(__file__).resolve().parents[1]
    return yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def tablas():
    """Distinguir presencia, utilizabilidad y ceros mediante tablas pequenas tipadas."""
    # String conserva el cero inicial; Int64 y Float64 admiten valores faltantes.
    codigos = pd.Series(["05001", "05002"], dtype="string")
    anios = pd.Series([2024, 2024], dtype="Int64")
    educacion = pd.DataFrame({
        "codigo_municipio": codigos.copy(), "anio": anios.copy(),
        "cobertura_neta": pd.Series([80, 105], dtype="Float64"),
        "desercion": pd.Series([2, pd.NA], dtype="Float64"),
        "reprobacion": pd.Series([0, 1], dtype="Float64"),
        "estado_cobertura_neta": pd.Series(["disponible", "pendiente_revision"], dtype="string"),
        "estado_desercion": pd.Series(["disponible", "faltante"], dtype="string"),
        "estado_reprobacion": pd.Series(["disponible", "disponible"], dtype="string"),
        "estado_homologacion": pd.Series(["pendiente_revision"] * 2, dtype="string"),
    })
    poblacion = pd.DataFrame({
        "codigo_municipio": codigos.copy(), "anio": anios.copy(),
        "poblacion_total": pd.Series([100, 0], dtype="Int64"),
        "poblacion_cabecera": pd.Series([80, 0], dtype="Int64"),
        "poblacion_centros_rural": pd.Series([20, 0], dtype="Int64"),
        "poblacion_consistente": pd.Series([True, True], dtype="boolean"),
        "estado_poblacion": pd.Series(["disponible", "disponible"], dtype="string"),
        "denominador_positivo": pd.Series([True, False], dtype="boolean"),
        "poblacion_para_ratios_utilizable": pd.Series([True, False], dtype="boolean"),
        "estado_homologacion": pd.Series(["pendiente_revision"] * 2, dtype="string"),
    })
    internet = pd.DataFrame({
        "codigo_municipio": codigos.copy(), "anio": anios.copy(),
        "accesos_t4": pd.Series([0, pd.NA], dtype="Int64"),
        # El 999 es un diagnostico parcial, nunca sustituto del total faltante.
        "accesos_validos_parcial": pd.Series([0, 999], dtype="Int64"),
        "estado_internet": pd.Series(["disponible", "no_utilizable"], dtype="string"),
        "accesos_para_indicadores_utilizables": pd.Series([True, False], dtype="boolean"),
        "estado_homologacion": pd.Series(["pendiente_revision"] * 2, dtype="string"),
    })
    divipola = pd.DataFrame({
        "codigo_municipio": codigos.copy(),
        "estado_catalogo": pd.Series(["disponible", "disponible"], dtype="string"),
        "tipo_territorio": pd.Series(["municipio", "municipio"], dtype="string"),
        "longitud": pd.Series([-75.58, pd.NA], dtype="Float64"),
        "latitud": pd.Series([6.24, pd.NA], dtype="Float64"),
    })
    return {"educacion": educacion, "poblacion": poblacion,
            "internet": internet, "divipola": divipola}


@pytest.fixture
def reportes(tablas):
    """Acompanar cada tabla con el resultado minimo de su preparacion previa."""
    return {nombre: {"filas_salida": len(datos)} for nombre, datos in tablas.items()}


@pytest.fixture
def metadata():
    """Describir una ejecucion sintetica sin afirmar aceptacion del panel final."""
    return {"etapa": "silver", "estado": "exploratorio", "ejecucion_id": "silver-prueba"}


@pytest.fixture
def raiz_temporal(tmp_path, configuracion):
    """Crear evidencia Bronze en una raiz temporal que ninguna salida debe cambiar."""
    bronze = tmp_path / configuracion["paths"]["bronze_dir"]
    bronze.mkdir(parents=True)
    (bronze / "original.txt").write_text("Fuente original de prueba", encoding="utf-8")
    return tmp_path


def reporte_calidad(tablas, reportes, configuracion):
    """Construir el reporte mediante la misma entrada que emplea el coordinador."""
    return construir_reporte_silver(tablas, reportes, configuracion, "silver-prueba")


def ruta_archivo(raiz, valor):
    """Aceptar que metadata describa las rutas absolutas o relativas a la raiz."""
    ruta = Path(valor)
    return ruta if ruta.is_absolute() else raiz / ruta


def salidas_previstas(raiz, configuracion):
    """Identificar solo los seis archivos finales, sin depender de nombres temporales."""
    silver = raiz / configuracion["paths"]["silver_dir"]
    logs = raiz / configuracion["paths"]["logs_dir"]
    rutas = [silver / configuracion["outputs"][nombre] for nombre in NOMBRES_SILVER.values()]
    return rutas + [logs / configuracion["outputs"]["quality_report"],
                    logs / configuracion["outputs"]["execution_metadata"]]


def test_calidad_distingue_presencia_y_utilizabilidad_por_fuente(tablas, reportes, configuracion):
    """Una tasa pendiente sigue presente, mientras un parcial no completa accesos."""
    original = {nombre: datos.copy(deep=True) for nombre, datos in tablas.items()}
    reporte = reporte_calidad(tablas, reportes, configuracion)
    for nombre, datos in tablas.items():
        pd.testing.assert_frame_equal(datos, original[nombre])
        controles = reporte["fuentes"][nombre]
        assert controles["filas"] == controles["codigos_distintos"] == 2
        assert controles["llaves_incompletas"] == controles["llaves_duplicadas"] == 0
        assert controles["llave"] == (["codigo_municipio"] if nombre == "divipola"
                                      else ["codigo_municipio", "anio"])
    cobertura = reporte["fuentes"]["educacion"]["criticas_en_fuente"]["cobertura_neta"]
    assert cobertura["denominador"] == 2
    assert cobertura["numerador_presencia_numerica"] == 2
    assert cobertura["porcentaje_presencia_numerica"] == 100
    assert cobertura["numerador_utilizables_fuente"] == 1
    assert cobertura["porcentaje_utilizables_fuente"] == 50
    accesos = reporte["fuentes"]["internet"]["criticas_en_fuente"]["accesos_t4"]
    assert accesos["numerador_presencia_numerica"] == 1
    assert accesos["numerador_utilizables_fuente"] == 1
    assert accesos["porcentaje_presencia_numerica"] == 50


def test_cero_poblacional_es_presente_sin_habilitar_division(tablas, reportes, configuracion):
    """La completitud de un conteo y la posibilidad de dividir por el son distintas."""
    reporte = reporte_calidad(tablas, reportes, configuracion)
    poblacion = reporte["fuentes"]["poblacion"]["criticas_en_fuente"]
    for nombre in ["poblacion_total", "poblacion_centros_rural"]:
        assert poblacion[nombre]["numerador_presencia_numerica"] == 2
        assert poblacion[nombre]["numerador_utilizables_fuente"] == 2
    assert reporte["fuentes"]["poblacion"]["controles_adicionales"]["poblacion_para_ratios_utilizable"] == 1
    assert tablas["poblacion"].loc[1, "poblacion_total"] == 0
    assert not bool(tablas["poblacion"].loc[1, "denominador_positivo"])
    assert not bool(tablas["poblacion"].loc[1, "poblacion_para_ratios_utilizable"])


def test_denominadores_locales_no_se_presentan_como_aceptacion_panel(tablas, reportes, configuracion):
    """Las filas de cada fuente no equivalen todavia al universo educativo integrado."""
    tablas["internet"] = tablas["internet"].iloc[:1].copy()
    reportes["internet"]["filas_salida"] = 1
    reporte = reporte_calidad(tablas, reportes, configuracion)
    assert reporte["fuentes"]["internet"]["criticas_en_fuente"]["accesos_t4"]["denominador"] == 1
    assert reporte["fuentes"]["educacion"]["criticas_en_fuente"]["cobertura_neta"]["denominador"] == 2
    assert reporte["estado"] == "exploratorio"
    aceptacion = reporte["aceptacion_panel"]
    assert aceptacion["estado"] == "no_evaluada"
    assert aceptacion["variables_criticas"] == configuracion["quality"]["critical_columns"]
    # Un porcentaje definitivo del panel no se puede calcular antes de integrarlo.
    for nombre in ["homologacion_panel", "completitud_seis_variables",
                   "completitud_conjunta", "coincidencia_internet_t4"]:
        assert aceptacion[nombre] is None
    for nombre in ["educacion", "poblacion", "internet"]:
        assert tablas[nombre]["estado_homologacion"].eq("pendiente_revision").all()
        cantidad = len(tablas[nombre])
        assert reporte["fuentes"][nombre]["estados"]["estado_homologacion"] == {
            "pendiente_revision": cantidad}
    json.dumps(reporte, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("fuente", list(NOMBRES_SILVER))
@pytest.mark.parametrize("problema", ["duplicada", "faltante", "cero", "corta"])
def test_calidad_rechaza_llaves_territoriales_invalidas(tablas, reportes, configuracion, fuente, problema):
    """La publicacion necesita codigos validos y llaves completas y unicas."""
    if problema == "duplicada":
        tablas[fuente] = pd.concat([tablas[fuente], tablas[fuente].iloc[:1]], ignore_index=True)
    else:
        tablas[fuente].loc[0, "codigo_municipio"] = {
            "faltante": pd.NA, "cero": "00000", "corta": "5001",
        }[problema]
    reportes[fuente]["filas_salida"] = len(tablas[fuente])
    with pytest.raises(ValueError):
        reporte_calidad(tablas, reportes, configuracion)


@pytest.mark.parametrize("fuente", ["educacion", "poblacion", "internet"])
@pytest.mark.parametrize("anio", [2017, 2025, pd.NA])
def test_calidad_rechaza_anios_fuera_del_contrato_o_ausentes(tablas, reportes, configuracion, fuente, anio):
    """Una fila anual publicada debe pertenecer al periodo definido y tener anio."""
    tablas[fuente].loc[0, "anio"] = anio
    with pytest.raises(ValueError):
        reporte_calidad(tablas, reportes, configuracion)


def test_exportacion_preserva_tipos_faltantes_ceros_y_huellas(
        tablas, reportes, configuracion, metadata, raiz_temporal):
    """Reabrir cada Parquet comprueba el artefacto publicado, no solo su escritura."""
    entradas = {nombre: datos.copy(deep=True) for nombre, datos in tablas.items()}
    reporte = reporte_calidad(tablas, reportes, configuracion)
    metadata_original = copy.deepcopy(metadata)
    reporte_original = copy.deepcopy(reporte)
    resultado = exportar_silver(tablas, reporte, metadata, configuracion, raiz_temporal)
    assert metadata == metadata_original
    assert reporte == reporte_original
    assert set(resultado["salidas"]) == set(NOMBRES_SILVER)
    for nombre, descripcion in resultado["salidas"].items():
        archivo = ruta_archivo(raiz_temporal, descripcion["archivo"])
        reabierta = pd.read_parquet(archivo)
        pd.testing.assert_frame_equal(reabierta, entradas[nombre], check_exact=True)
        pd.testing.assert_frame_equal(tablas[nombre], entradas[nombre], check_exact=True)
        assert descripcion["filas"] == len(entradas[nombre])
        assert descripcion["columnas"] == [
            {"nombre": columna, "tipo": str(tipo)} for columna, tipo in entradas[nombre].dtypes.items()
        ]
        assert descripcion["tamano_bytes"] == archivo.stat().st_size
        assert descripcion["sha256"] == hashlib.sha256(archivo.read_bytes()).hexdigest()
    # Los JSON deben usar null para faltantes y mantener su trazabilidad verificable.
    calidad = resultado["reporte_calidad"]
    archivo_calidad = ruta_archivo(raiz_temporal, calidad["archivo"])
    assert json.loads(archivo_calidad.read_text(encoding="utf-8")) == reporte
    assert calidad["sha256"] == hashlib.sha256(archivo_calidad.read_bytes()).hexdigest()
    assert calidad["tamano_bytes"] == archivo_calidad.stat().st_size
    archivo_metadata = ruta_archivo(raiz_temporal, resultado["metadata_ejecucion"]["archivo"])
    assert json.loads(archivo_metadata.read_text(encoding="utf-8")) == resultado
    assert (raiz_temporal / configuracion["paths"]["bronze_dir"] / "original.txt").read_text(
        encoding="utf-8") == "Fuente original de prueba"
    assert not (raiz_temporal / configuracion["paths"]["gold_dir"]).exists()


@pytest.mark.parametrize("destino", ["metadata", "calidad"])
def test_json_no_finito_impide_publicar_archivos(
        tablas, reportes, configuracion, metadata, raiz_temporal, destino):
    """NaN es invalido en JSON estricto y debe fallar antes de publicar la ejecucion."""
    reporte = reporte_calidad(tablas, reportes, configuracion)
    (metadata if destino == "metadata" else reporte)["valor_no_finito"] = float("nan")
    with pytest.raises(ValueError):
        exportar_silver(tablas, reporte, metadata, configuracion, raiz_temporal)
    assert not any(ruta.exists() for ruta in salidas_previstas(raiz_temporal, configuracion))


@pytest.mark.parametrize("fallo", ["escritura", "verificacion"])
def test_fallo_previo_a_publicacion_no_deja_salida_parcial(
        tablas, reportes, configuracion, metadata, raiz_temporal, monkeypatch, fallo):
    """Una falla al escribir o reabrir no debe publicar ninguna de las seis salidas."""
    def fallar(*args, **kwargs):
        """Simular un error del almacenamiento sin depender de sus archivos temporales."""
        raise OSError("Error de almacenamiento simulado")

    # Inyectamos en la API publica de pandas, independientemente de la estrategia temporal.
    if fallo == "escritura":
        monkeypatch.setattr(pd.DataFrame, "to_parquet", fallar)
    else:
        monkeypatch.setattr(pd, "read_parquet", fallar)
    reporte = reporte_calidad(tablas, reportes, configuracion)
    with pytest.raises(OSError):
        exportar_silver(tablas, reporte, metadata, configuracion, raiz_temporal)
    assert not any(ruta.exists() for ruta in salidas_previstas(raiz_temporal, configuracion))


def test_fallo_de_publicacion_restaura_las_seis_salidas_anteriores(
        tablas, reportes, configuracion, metadata, raiz_temporal, monkeypatch):
    """Un cambio incompleto no debe mezclar tablas nuevas con reportes anteriores."""
    reporte = reporte_calidad(tablas, reportes, configuracion)
    exportar_silver(tablas, reporte, metadata, configuracion, raiz_temporal)
    finales = salidas_previstas(raiz_temporal, configuracion)
    anteriores = {ruta: ruta.read_bytes() for ruta in finales}
    objetivo = (raiz_temporal / configuracion["paths"]["silver_dir"] /
                configuracion["outputs"]["internet_silver"]).resolve()
    reemplazar_real = Path.replace
    fallo_inyectado = []

    def reemplazar_con_fallo(origen, destino):
        """Fallar una sola publicacion y permitir despues la restauracion de backups."""
        if Path(destino).resolve() == objetivo and not fallo_inyectado:
            fallo_inyectado.append(True)
            raise OSError("Fallo al publicar internet")
        return reemplazar_real(origen, destino)

    candidatas = {nombre: datos.copy(deep=True) for nombre, datos in tablas.items()}
    candidatas["educacion"].loc[0, "cobertura_neta"] = 81
    metadata_nueva = copy.deepcopy(metadata)
    metadata_nueva["ejecucion_id"] = "silver-segunda-prueba"
    reporte_nuevo = reporte_calidad(candidatas, reportes, configuracion)
    monkeypatch.setattr(Path, "replace", reemplazar_con_fallo)
    with pytest.raises(OSError):
        exportar_silver(candidatas, reporte_nuevo, metadata_nueva, configuracion, raiz_temporal)
    assert fallo_inyectado
    for ruta, contenido in anteriores.items():
        assert ruta.read_bytes() == contenido


def test_parquet_reabierto_distinto_impide_publicacion(
        tablas, reportes, configuracion, metadata, raiz_temporal, monkeypatch):
    """Una escritura que produce otros datos no puede darse por correctamente verificada."""
    leer_real = pd.read_parquet

    def leer_con_valor_alterado(*args, **kwargs):
        """Simular un artefacto legible que cambio un valor durante la persistencia."""
        recuperada = leer_real(*args, **kwargs)
        if "cobertura_neta" in recuperada.columns:
            recuperada.loc[0, "cobertura_neta"] = 81
        return recuperada

    # El problema ocurre en la primera tabla y debe detener la publicacion completa.
    monkeypatch.setattr(pd, "read_parquet", leer_con_valor_alterado)
    reporte = reporte_calidad(tablas, reportes, configuracion)
    with pytest.raises(AssertionError):
        exportar_silver(tablas, reporte, metadata, configuracion, raiz_temporal)
    assert not any(ruta.exists() for ruta in salidas_previstas(raiz_temporal, configuracion))


@pytest.mark.parametrize("problema", ["nombre_repetido", "json_repetido", "nombre_con_ruta",
                                       "silver_bronze", "silver_gold", "silver_fuera",
                                       "logs_bronze", "logs_gold"])
def test_exportacion_rechaza_rutas_inseguras_o_colisiones(
        tablas, reportes, configuracion, metadata, raiz_temporal, problema):
    """Las salidas no pueden reemplazar fuentes, invadir Gold ni escapar de la raiz."""
    reporte = reporte_calidad(tablas, reportes, configuracion)
    reglas = copy.deepcopy(configuracion)
    if problema == "nombre_repetido":
        reglas["outputs"]["internet_silver"] = reglas["outputs"]["education_silver"]
    elif problema == "json_repetido":
        reglas["outputs"]["execution_metadata"] = reglas["outputs"]["quality_report"]
    elif problema == "nombre_con_ruta":
        reglas["outputs"]["education_silver"] = "../bronze/educacion.parquet"
    elif problema.startswith("silver_"):
        reglas["paths"]["silver_dir"] = {
            "silver_bronze": reglas["paths"]["bronze_dir"],
            "silver_gold": reglas["paths"]["gold_dir"], "silver_fuera": "../fuera",
        }[problema]
    else:
        reglas["paths"]["logs_dir"] = reglas["paths"][
            "bronze_dir" if problema == "logs_bronze" else "gold_dir"]
    with pytest.raises(ValueError):
        exportar_silver(tablas, reporte, metadata, reglas, raiz_temporal)
    assert (raiz_temporal / configuracion["paths"]["bronze_dir"] / "original.txt").read_text(
        encoding="utf-8") == "Fuente original de prueba"
    assert not any(ruta.exists() for ruta in salidas_previstas(raiz_temporal, configuracion))


def test_main_selecciona_silver_sin_leer_fuentes(monkeypatch, capsys):
    """El comando debe invocar el coordinador de las cuatro fuentes una sola vez."""
    import main as pipeline

    resultado = {"ejecucion_id": "solo-prueba"}
    llamadas = []

    def ejecutar_sintetico(ruta_configuracion):
        """Representar una ejecucion Silver sin recorrer ni escribir archivos reales."""
        llamadas.append(("ejecutar", ruta_configuracion))
        return resultado

    def mostrar_sintetico(metadata_recibida):
        """Comprobar que la presentacion recibe la ejecucion recien completada."""
        assert metadata_recibida is resultado
        llamadas.append(("mostrar", None))

    def fuente_individual(*args, **kwargs):
        """Una seleccion individual accidental debe fallar antes de leer Bronze."""
        pytest.fail("--silver intento ejecutar una fuente individual desde el selector")

    monkeypatch.setattr(pipeline, "ejecutar_silver", ejecutar_sintetico)
    monkeypatch.setattr(pipeline, "_mostrar_silver", mostrar_sintetico)
    for nombre in ["ejecutar_educacion", "ejecutar_poblacion", "ejecutar_internet", "ejecutar_divipola"]:
        monkeypatch.setattr(pipeline, nombre, fuente_individual)
    monkeypatch.setattr("sys.argv", ["main.py", "--silver"])
    pipeline.main()
    assert llamadas == [("ejecutar", None), ("mostrar", None)]
    # El selector Silver no debe anunciar que todo quedo unicamente en memoria.
    assert "Resultado en memoria" not in capsys.readouterr().out


def test_main_rechaza_silver_junto_con_fuente_individual(monkeypatch):
    """Dos modos incompatibles requieren un error claro del parser de argumentos."""
    import main as pipeline

    monkeypatch.setattr("sys.argv", ["main.py", "--silver", "--fuente", "internet"])
    with pytest.raises(SystemExit) as error:
        pipeline.main()
    assert error.value.code == 2


@pytest.mark.parametrize("fuente,columna", [
    ("educacion", "cobertura_neta"), ("poblacion", "poblacion_total"),
    ("internet", "accesos_t4"),
])
def test_calidad_rechaza_criticas_guardadas_como_texto(
        tablas, reportes, configuracion, fuente, columna):
    """Una cadena convertible no satisface el esquema numerico prometido por Silver."""
    # Los textos siguen pareciendo numeros, pero persistirlos alteraria su uso posterior.
    tablas[fuente][columna] = tablas[fuente][columna].astype("string")
    with pytest.raises(ValueError):
        reporte_calidad(tablas, reportes, configuracion)


def test_calidad_rechaza_banderas_textuales_y_estados_sin_tipo_string(
        tablas, reportes, configuracion):
    """Evitar interpretar texto como booleano o aceptar estados con un esquema generico."""
    alteraciones = [
        ("poblacion", "poblacion_consistente", "string"),
        ("educacion", "estado_cobertura_neta", "object"),
    ]
    for fuente, columna, tipo in alteraciones:
        # Cada alteracion se prueba por separado: una falla no debe ocultar la siguiente.
        candidatas = {nombre: datos.copy(deep=True) for nombre, datos in tablas.items()}
        candidatas[fuente][columna] = candidatas[fuente][columna].astype(tipo)
        with pytest.raises(ValueError):
            reporte_calidad(candidatas, reportes, configuracion)


def preparar_entradas_metadata(raiz, configuracion):
    """Crear cuatro archivos de prueba cuya integridad pueda comprobarse sin leerlos."""
    rutas = {}
    for nombre in ["education_stats", "population", "internet_access", "divipola"]:
        ruta = raiz / configuracion["sources"][nombre]["path"]
        ruta.parent.mkdir(parents=True, exist_ok=True)
        # La captura de integridad examina bytes; no necesita CSV o Excel reales.
        ruta.write_bytes(("original " + nombre).encode("utf-8"))
        rutas[nombre] = ruta
    ruta_config = raiz / "config" / "config.yaml"
    ruta_config.parent.mkdir(parents=True, exist_ok=True)
    ruta_config.write_text(yaml.safe_dump(configuracion, allow_unicode=True), encoding="utf-8")
    return rutas, ruta_config


def test_metadata_detecta_cambio_de_fuente_aunque_conserve_tamano(configuracion, tmp_path):
    """La huella debe detectar contenido distinto, incluso cuando el tamano es igual."""
    rutas, ruta_config = preparar_entradas_metadata(tmp_path, configuracion)
    entradas_antes = capturar_entradas(configuracion, tmp_path)
    huella_config = hashlib.sha256(ruta_config.read_bytes()).hexdigest()
    fuente = rutas["internet_access"]
    anteriores = fuente.read_bytes()
    fuente.write_bytes(anteriores.replace(b"original", b"alterada"))
    assert fuente.stat().st_size == len(anteriores)
    # La deteccion ocurre antes de consultar Git: no se requiere repositorio ni red.
    with pytest.raises(ValueError):
        crear_metadata_silver(configuracion, tmp_path, ruta_config, "silver-prueba",
                              "2026-10-06T00:00:00Z", entradas_antes,
                              huella_configuracion=huella_config)


def test_metadata_detecta_cambio_del_yaml_durante_preparacion(configuracion, tmp_path):
    """Una configuracion modificada no puede atribuirse a la ejecucion ya preparada."""
    _, ruta_config = preparar_entradas_metadata(tmp_path, configuracion)
    entradas_antes = capturar_entradas(configuracion, tmp_path)
    huella_config = hashlib.sha256(ruta_config.read_bytes()).hexdigest()
    contenido = ruta_config.read_text(encoding="utf-8")
    # Cambiar solo un comentario prueba que la integridad se refiere a los bytes reales.
    ruta_config.write_text(contenido + "\n# Cambio durante la preparacion.\n", encoding="utf-8")
    with pytest.raises(ValueError):
        crear_metadata_silver(configuracion, tmp_path, ruta_config, "silver-prueba",
                              "2026-10-06T00:00:00Z", entradas_antes,
                              huella_configuracion=huella_config)
