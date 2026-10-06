"""Pruebas de reglas que podrian cambiar o perder datos educativos."""

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.extract.extract_education import extraer_educacion
from src.transform.clean_education import limpiar_educacion


@pytest.fixture
def configuracion():
    """Usar las mismas reglas configuradas para el proyecto real."""
    # Leemos sin modificar el YAML; cada prueba recibe su propia copia.
    raiz = Path(__file__).resolve().parents[1]
    return yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def muestra():
    """Incluir un codigo corto, miles, un nacional y un anio fuera del periodo."""
    # Son datos sinteticos para provocar problemas sin tocar los archivos Bronze.
    filas = [
        ["2024", "5001", " Medellin ", "5", "Antioquia", "1000", "95", "110", "0", "4"],
        ["2021", "11001", "Bogota", "11", "Bogota", "1,174,274", "105", "120", None, "5"],
        ["2019", "0", "NACIONAL", "0", "NACIONAL", "3000", "90", "100", "2", "3"],
        ["2017", "05002", "Abejorral", "05", "Antioquia", "500", "80", "90", "3", "4"],
    ]
    return pd.DataFrame(filas, columns=[
        "AÑO", "CÓDIGO_MUNICIPIO", "MUNICIPIO", "CÓDIGO_DEPARTAMENTO", "DEPARTAMENTO",
        "POBLACIÓN_5_16", "COBERTURA_NETA", "COBERTURA_BRUTA", "DESERCIÓN", "REPROBACIÓN",
    ], dtype="string")


def test_extractor_conserva_datos_y_archivo(tmp_path, configuracion, muestra):
    """La extraccion debe conservar textos, faltantes y el archivo de entrada."""
    # Creamos un CSV temporal. La huella de bytes detecta cualquier sobrescritura.
    ruta = tmp_path / "educacion.csv"
    muestra.to_csv(ruta, index=False, encoding="utf-8-sig")
    bytes_originales = ruta.read_bytes()
    fuente = copy.deepcopy(configuracion["sources"]["education_stats"])
    fuente["path"] = ruta.name
    extraidos = extraer_educacion(fuente, tmp_path)
    pd.testing.assert_frame_equal(extraidos, muestra)
    assert ruta.read_bytes() == bytes_originales


def test_extractor_detecta_columna_ausente(tmp_path, configuracion, muestra):
    """Una fuente sin un indicador obligatorio debe fallar antes de limpiar."""
    ruta = tmp_path / "incompleta.csv"
    muestra.drop(columns="DESERCIÓN").to_csv(ruta, index=False, encoding="utf-8-sig")
    fuente = copy.deepcopy(configuracion["sources"]["education_stats"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError, match="obligatorias"):
        extraer_educacion(fuente, tmp_path)


def test_extractor_detecta_encabezado_repetido(tmp_path, configuracion):
    """No permitir que pandas oculte un encabezado duplicado renombrando columnas."""
    ruta = tmp_path / "repetida.csv"
    ruta.write_text("AÑO,AÑO\n2024,2024\n", encoding="utf-8-sig")
    fuente = copy.deepcopy(configuracion["sources"]["education_stats"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError, match="repite encabezados"):
        extraer_educacion(fuente, tmp_path)


def test_limpieza_conserva_original_y_aplica_periodo(configuracion, muestra):
    """No alterar la entrada, perder ceros ni mezclar nacionales con territorios."""
    original = muestra.copy(deep=True)
    limpia, reporte = limpiar_educacion(muestra, configuracion)
    pd.testing.assert_frame_equal(muestra, original)
    assert limpia["codigo_municipio"].tolist() == ["05001", "11001"]
    assert limpia["codigo_departamento"].tolist() == ["05", "11"]
    assert limpia["registro_origen"].tolist() == [1, 2]
    assert limpia.loc[0, "codigo_municipio_original"] == "5001"
    assert reporte["registros_nacionales_separados"] == 1
    assert reporte["registros_territoriales_fuera_periodo"] == 1
    assert limpia["estado_homologacion"].eq("pendiente_revision").all()


def test_miles_y_faltantes_no_se_imputan(configuracion, muestra):
    """Corregir agrupacion de miles valida sin inventar una tasa ausente."""
    limpia, reporte = limpiar_educacion(muestra, configuracion)
    assert limpia.loc[1, "poblacion_5_16"] == 1174274
    assert limpia.loc[1, "poblacion_5_16_original"] == "1,174,274"
    assert reporte["poblacion_5_16_miles_corregidos"] == 1
    assert pd.isna(limpia.loc[1, "desercion"])
    assert limpia.loc[1, "estado_desercion"] == "faltante"


@pytest.mark.parametrize("valor,esperado", [("379.616", 379616), ("1.174.274", 1174274)])
def test_puntos_de_miles_solo_en_conteos(configuracion, muestra, valor, esperado):
    """Reconocer grupos completos de miles sin retirar decimales de las tasas."""
    muestra.loc[0, "POBLACIÓN_5_16"] = valor
    muestra.loc[0, "DESERCIÓN"] = "5.234"
    limpia, reporte = limpiar_educacion(muestra, configuracion)
    assert limpia.loc[0, "poblacion_5_16"] == esperado
    assert limpia.loc[0, "desercion"] == pytest.approx(5.234)
    assert reporte["poblacion_5_16_miles_por_separador"]["punto"] == 1


def test_coberturas_no_se_recortan(configuracion, muestra):
    """La metodologia MEN admite neta >100: conservarla con marca informativa."""
    limpia, reporte = limpiar_educacion(muestra, configuracion)
    assert limpia.loc[1, "cobertura_neta"] == 105
    assert limpia.loc[1, "estado_cobertura_neta"] == "disponible"
    assert bool(limpia.loc[1, "cobertura_neta_superior_100_informativo"])
    assert not bool(limpia.loc[0, "cobertura_neta_superior_100_informativo"])
    assert limpia.loc[1, "cobertura_bruta"] == 120
    assert reporte["coberturas_brutas_superiores_100_informativo"] == 2
    assert reporte["completitud_criticas_educativas"]["cobertura_neta"]["valores_utilizables"] == 2
    assert reporte["coberturas_netas_superiores_100_informativo"] == 1


def test_duplicado_tras_normalizar_detiene_proceso(configuracion, muestra):
    """5001 y 05001 en el mismo anio representan una llave repetida."""
    repetida = muestra.iloc[[0]].copy()
    repetida["CÓDIGO_MUNICIPIO"] = "05001"
    entrada = pd.concat([muestra, repetida], ignore_index=True)
    with pytest.raises(ValueError, match="duplicada"):
        limpiar_educacion(entrada, configuracion)


@pytest.mark.parametrize("codigo", ["50A01", None, "", "050001"])
def test_codigo_municipal_invalido_no_desaparece(configuracion, muestra, codigo):
    """Una llave invalida debe detenerse, no desaparecer mediante un filtro."""
    muestra.loc[0, "CÓDIGO_MUNICIPIO"] = codigo
    with pytest.raises(ValueError, match="codigos municipales"):
        limpiar_educacion(muestra, configuracion)


@pytest.mark.parametrize("anio", ["texto", None, "2024.5", "inf"])
def test_anio_invalido_no_desaparece(configuracion, muestra, anio):
    """Los anios no legibles o no enteros no se cuentan como fuera del periodo."""
    muestra.loc[0, "AÑO"] = anio
    with pytest.raises(ValueError, match="anios incompletos"):
        limpiar_educacion(muestra, configuracion)


@pytest.mark.parametrize("valor", ["1,17,274", "12.5", "7.74", "-5", "inf"])
def test_poblacion_no_utilizable_conserva_evidencia(configuracion, muestra, valor):
    """No interpretar conteos fraccionarios, negativos o mal agrupados como poblacion."""
    muestra.loc[0, "POBLACIÓN_5_16"] = valor
    limpia, _ = limpiar_educacion(muestra, configuracion)
    assert pd.isna(limpia.loc[0, "poblacion_5_16"])
    assert limpia.loc[0, "poblacion_5_16_original"] == valor
    assert limpia.loc[0, "poblacion_5_16_no_utilizable"]


@pytest.mark.parametrize("valor,estado", [
    ("texto", "no_numerico"), ("inf", "no_utilizable"),
    ("-1", "no_utilizable"), ("101", "no_utilizable"),
])
def test_tasa_no_utilizable_se_identifica(configuracion, muestra, valor, estado):
    """La presencia de un texto o un numero no garantiza una tasa utilizable."""
    muestra.loc[0, "DESERCIÓN"] = valor
    limpia, _ = limpiar_educacion(muestra, configuracion)
    assert limpia.loc[0, "estado_desercion"] == estado
    assert limpia.loc[0, "desercion_original"] == valor


def test_nacional_necesita_evidencia(configuracion, muestra):
    """Codigo cero con departamento territorial no debe eliminarse como nacional."""
    muestra.loc[2, "DEPARTAMENTO"] = "Antioquia"
    with pytest.raises(ValueError, match="registros nacionales"):
        limpiar_educacion(muestra, configuracion)


def test_nacional_sin_nombre_no_se_separa(configuracion, muestra):
    """El codigo cero no basta si falta el nombre que respalda el total nacional."""
    # Una comparacion con pd.NA no debe hacer desaparecer esta contradiccion.
    muestra.loc[2, "MUNICIPIO"] = pd.NA
    with pytest.raises(ValueError, match="registros nacionales"):
        limpiar_educacion(muestra, configuracion)


def test_colombia_huila_es_un_municipio(configuracion, muestra):
    """El nombre Colombia no convierte al municipio 41206 en un total nacional."""
    # Este caso proviene del contraste con la fuente real y evita perder filas.
    muestra.loc[0, "MUNICIPIO"] = "Colombia"
    muestra.loc[0, "CÓDIGO_MUNICIPIO"] = "41206"
    muestra.loc[0, "CÓDIGO_DEPARTAMENTO"] = "41"
    muestra.loc[0, "DEPARTAMENTO"] = "Huila"
    limpia, reporte = limpiar_educacion(muestra, configuracion)
    assert "41206" in limpia["codigo_municipio"].values
    assert reporte["registros_nacionales_separados"] == 1


def test_encabezados_normalizados_no_colisionan(configuracion, muestra):
    """No aceptar dos columnas diferentes que terminan llamandose anio."""
    muestra["ano"] = muestra["AÑO"]
    with pytest.raises(ValueError, match="nombre normalizado"):
        limpiar_educacion(muestra, configuracion)


def test_columnas_desconocidas_se_conservan_y_reporte_es_json(configuracion, muestra):
    """Una columna nueva permanece textual y el reporte no contiene NaN de JSON."""
    muestra["OBSERVACIÓN"] = " texto nuevo "
    limpia, reporte = limpiar_educacion(muestra, configuracion)
    assert limpia["observacion"].eq("texto nuevo").all()
    assert "observacion" in reporte["columnas_nuevas_no_tipificadas"]
    json.dumps(reporte, ensure_ascii=False, allow_nan=False)
