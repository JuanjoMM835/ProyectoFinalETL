"""Pruebas que evitan perder territorios o atribuir certeza al catalogo DIVIPOLA."""

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.extract.extract_divipola import extraer_divipola
from src.transform.clean_divipola import limpiar_divipola


TIPO_FUENTE = "Tipo: Municipio / Isla / Área no municipalizada"


@pytest.fixture
def configuracion():
    """Leer las reglas del proyecto sin modificar el archivo de configuracion."""
    # Cada prueba recibe una lectura independiente para evitar cambios compartidos.
    raiz = Path(__file__).resolve().parents[1]
    return yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def muestra():
    """Incluir municipio, area no municipalizada e isla con distintas coordenadas."""
    # Son filas sinteticas: las pruebas nunca escriben sobre los archivos Bronze.
    filas = [
        ["5001", " Medellín ", "5", " Antioquia ", " Municipio ", "-75,58", "6.24"],
        ["91405", "La Chorrera", "91", "Amazonas", "Área no municipalizada", "-72.78", "-0,90"],
        ["88564", "Isla de prueba", "88", "San Andrés", "Isla", "0", "0"],
    ]
    return pd.DataFrame(filas, columns=[
        "Código Municipio", "Nombre Municipio", "Código Departamento",
        "Nombre Departamento", TIPO_FUENTE, "longitud", "Latitud",
    ], dtype="string")


def test_extractor_conserva_textos_y_archivo(tmp_path, configuracion, muestra):
    """Leer los codigos como texto sin sobrescribir la fuente ni quitar sus espacios."""
    ruta = tmp_path / "divipola.csv"
    muestra.to_csv(ruta, index=False, encoding="utf-8-sig")
    bytes_originales = ruta.read_bytes()
    fuente = copy.deepcopy(configuracion["sources"]["divipola"])
    fuente["path"] = ruta.name
    extraidos = extraer_divipola(fuente, tmp_path)
    pd.testing.assert_frame_equal(extraidos, muestra)
    assert ruta.read_bytes() == bytes_originales


def test_extractor_detecta_columna_obligatoria_ausente(tmp_path, configuracion, muestra):
    """La ausencia del tipo territorial no debe pasar inadvertida en la extraccion."""
    ruta = tmp_path / "incompleta.csv"
    muestra.drop(columns=TIPO_FUENTE).to_csv(ruta, index=False, encoding="utf-8-sig")
    fuente = copy.deepcopy(configuracion["sources"]["divipola"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        extraer_divipola(fuente, tmp_path)


def test_extractor_detecta_encabezado_repetido(tmp_path, configuracion, muestra):
    """Detectar repetidos antes de que pandas los renombre automaticamente."""
    ruta = tmp_path / "repetida.csv"
    # Conservamos todas las columnas obligatorias para provocar solo la repeticion.
    repetida = pd.concat([muestra, muestra[["Código Municipio"]]], axis=1)
    repetida.to_csv(ruta, index=False, encoding="utf-8-sig")
    fuente = copy.deepcopy(configuracion["sources"]["divipola"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        extraer_divipola(fuente, tmp_path)


def test_limpieza_conserva_entrada_tildes_codigos_y_territorios(configuracion, muestra):
    """Conservar las tres clases territoriales y los originales sin modificar la entrada."""
    original = muestra.copy(deep=True)
    catalogo, reporte = limpiar_divipola(muestra, configuracion)
    pd.testing.assert_frame_equal(muestra, original)
    assert catalogo["codigo_municipio"].tolist() == ["05001", "91405", "88564"]
    assert catalogo["codigo_departamento"].tolist() == ["05", "91", "88"]
    assert catalogo["municipio"].tolist() == ["Medellín", "La Chorrera", "Isla de prueba"]
    assert catalogo.loc[0, "departamento"] == "Antioquia"
    assert catalogo["tipo_territorio"].tolist() == ["municipio", "area_no_municipalizada", "isla"]
    assert catalogo["registro_origen"].tolist() == [1, 2, 3]
    assert catalogo.loc[0, "codigo_municipio_original"] == "5001"
    assert catalogo.loc[0, "municipio_original"] == " Medellín "
    assert catalogo.loc[0, "codigo_departamento_original"] == "5"
    assert catalogo.loc[0, "departamento_original"] == " Antioquia "
    assert catalogo.loc[0, "tipo_territorio_original"] == " Municipio "
    assert str(catalogo["codigo_municipio"].dtype) == "string"
    assert str(catalogo["codigo_departamento"].dtype) == "string"
    assert catalogo["estado_catalogo"].eq("disponible").all()
    assert reporte["filas_entrada"] == reporte["filas_salida"] == 3
    assert reporte["claves_duplicadas"] == 0


def test_catalogo_no_inventa_anios_ni_homologacion_historica(configuracion, muestra):
    """Un catalogo territorial disponible no demuestra vigencia para todos los anios."""
    catalogo, _ = limpiar_divipola(muestra, configuracion)
    assert "anio" not in catalogo.columns
    assert "estado_homologacion" not in catalogo.columns
    assert len(catalogo) == 3


def test_duplicado_tras_normalizar_detiene_proceso(configuracion, muestra):
    """5001 y 05001 representan el mismo codigo aun sin columna de anio."""
    repetida = muestra.iloc[[0]].copy()
    repetida["Código Municipio"] = "05001"
    with pytest.raises(ValueError, match="duplicad"):
        limpiar_divipola(pd.concat([muestra, repetida], ignore_index=True), configuracion)


@pytest.mark.parametrize("codigo", [None, "", "0", "50A01", "050001"])
def test_codigo_municipal_invalido_no_desaparece(configuracion, muestra, codigo):
    """Una llave imposible debe detener la limpieza, no eliminar su territorio."""
    muestra.loc[0, "Código Municipio"] = codigo
    with pytest.raises(ValueError):
        limpiar_divipola(muestra, configuracion)


@pytest.mark.parametrize("codigo", [None, "XX", "11"])
def test_departamento_inconsistente_se_conserva_para_revision(configuracion, muestra, codigo):
    """Conservar el municipio aunque falte el departamento o contradiga el prefijo."""
    muestra.loc[0, "Código Departamento"] = codigo
    catalogo, reporte = limpiar_divipola(muestra, configuracion)
    medellin = catalogo.iloc[0]
    assert medellin["codigo_municipio"] == "05001"
    assert medellin["departamento_inconsistente"]
    assert medellin["estado_catalogo"] == "pendiente_revision"
    assert reporte["departamentos_inconsistentes"] == 1
    if codigo == "11":
        # No sustituimos un codigo contradictorio por el prefijo que esperamos.
        assert medellin["codigo_departamento"] == "11"
    else:
        assert pd.isna(medellin["codigo_departamento"])


@pytest.mark.parametrize("columna", ["Nombre Municipio", "Nombre Departamento"])
def test_nombre_ausente_no_se_imputa_ni_elimina(configuracion, muestra, columna):
    """Una fila identificable se conserva aunque sus metadatos esten incompletos."""
    muestra.loc[0, columna] = pd.NA
    catalogo, reporte = limpiar_divipola(muestra, configuracion)
    assert len(catalogo) == 3
    assert catalogo.loc[0, "metadatos_incompletos"]
    assert catalogo.loc[0, "estado_catalogo"] == "pendiente_revision"
    assert reporte["metadatos_incompletos"] == 1
    salida = "municipio" if columna == "Nombre Municipio" else "departamento"
    assert pd.isna(catalogo.loc[0, salida])


@pytest.mark.parametrize("nombre,conflicto", [("ANTIOQUIA", False), ("Otro departamento", True)])
def test_codigo_departamental_tiene_un_nombre_coherente(configuracion, muestra, nombre, conflicto):
    """Dos municipios del mismo departamento no deben atribuirle nombres contradictorios."""
    segunda = muestra.iloc[[0]].copy()
    segunda["Código Municipio"] = "05002"
    segunda["Nombre Municipio"] = "Abejorral"
    segunda["Nombre Departamento"] = nombre
    entrada = pd.concat([muestra, segunda], ignore_index=True)
    catalogo, reporte = limpiar_divipola(entrada, configuracion)
    antioquia = catalogo.loc[catalogo["codigo_departamento"].eq("05")]
    # La mayuscula es una variante de escritura; otro nombre requiere revision.
    assert antioquia["departamento_nombre_inconsistente"].eq(conflicto).all()
    assert reporte["filas_con_nombre_departamental_inconsistente"] == (2 if conflicto else 0)
    esperado = "pendiente_revision" if conflicto else "disponible"
    assert antioquia["estado_catalogo"].eq(esperado).all()


@pytest.mark.parametrize("tipo", ["Territorio experimental", None])
def test_tipo_desconocido_se_preserva_y_no_se_asume_municipio(configuracion, muestra, tipo):
    """Una categoria nueva o vacia no debe clasificarse mediante una suposicion."""
    muestra.loc[0, TIPO_FUENTE] = tipo
    catalogo, _ = limpiar_divipola(muestra, configuracion)
    assert len(catalogo) == 3
    assert catalogo.loc[0, "tipo_territorio"] == "no_resuelto"
    assert catalogo.loc[0, "tipo_no_resuelto"]
    assert catalogo.loc[0, "estado_catalogo"] == "pendiente_revision"


@pytest.mark.parametrize("tipo,esperado", [
    (" MUNICIPIO ", "municipio"),
    ("  area   NO municipalizada  ", "area_no_municipalizada"),
    (" ÍSLA ", "isla"),
])
def test_categoria_reconoce_acentos_mayusculas_y_espacios(configuracion, muestra, tipo, esperado):
    """Normalizar formas equivalentes sin modificar el texto que demuestra su origen."""
    muestra.loc[0, TIPO_FUENTE] = tipo
    catalogo, _ = limpiar_divipola(muestra, configuracion)
    assert catalogo.loc[0, "tipo_territorio"] == esperado
    assert catalogo.loc[0, "tipo_territorio_original"] == tipo
    assert not catalogo.loc[0, "tipo_no_resuelto"]


def test_coordenadas_decimales_y_cero_conservan_evidencia(configuracion, muestra):
    """Interpretar coma o punto decimal sin convertir el cero observado en faltante."""
    catalogo, _ = limpiar_divipola(muestra, configuracion)
    assert catalogo.loc[0, "longitud"] == pytest.approx(-75.58)
    assert catalogo.loc[0, "latitud"] == pytest.approx(6.24)
    assert catalogo.loc[1, "latitud"] == pytest.approx(-0.90)
    assert catalogo.loc[0, "longitud_original"] == "-75,58"
    assert catalogo.loc[0, "latitud_original"] == "6.24"
    assert catalogo.loc[2, "longitud"] == catalogo.loc[2, "latitud"] == 0
    assert catalogo["coordenadas_utilizables"].all()
    assert str(catalogo["longitud"].dtype) == "Float64"
    assert str(catalogo["latitud"].dtype) == "Float64"


@pytest.mark.parametrize("columna,valor,estado", [
    ("Latitud", None, "faltante"),
    ("Latitud", "texto", "no_numerico"),
    ("Latitud", "1,2.3", "no_numerico"),
    ("Latitud", "inf", "no_utilizable"),
    ("Latitud", "91", "no_utilizable"),
    ("longitud", "-181", "no_utilizable"),
])
def test_coordenada_invalida_se_marca_sin_invalidar_identidad(configuracion, muestra, columna, valor, estado):
    """El catalogo puede servir para codigos aunque una coordenada no sirva para mapas."""
    muestra.loc[0, columna] = valor
    catalogo, _ = limpiar_divipola(muestra, configuracion)
    salida = columna.lower()
    assert pd.isna(catalogo.loc[0, salida])
    assert catalogo.loc[0, "estado_" + salida] == estado
    assert not catalogo.loc[0, "coordenadas_utilizables"]
    assert catalogo.loc[0, "estado_catalogo"] == "disponible"
    if valor is not None:
        assert catalogo.loc[0, salida + "_original"] == valor


def test_limites_geograficos_validos_no_se_recortan(configuracion, muestra):
    """Los extremos admitidos son datos validos, no valores que deban ajustarse."""
    muestra.loc[0, "Latitud"] = "-90"
    muestra.loc[0, "longitud"] = "180"
    catalogo, _ = limpiar_divipola(muestra, configuracion)
    assert catalogo.loc[0, "latitud"] == -90
    assert catalogo.loc[0, "longitud"] == 180
    assert catalogo.loc[0, "coordenadas_utilizables"]


def test_coordenadas_opcionales_no_se_inventan(configuracion, muestra):
    """Una fuente sin coordenadas sigue siendo catalogo y no recibe numeros ficticios."""
    sin_coordenadas = muestra.drop(columns=["longitud", "Latitud"])
    catalogo, _ = limpiar_divipola(sin_coordenadas, configuracion)
    assert "longitud" not in catalogo.columns
    assert "latitud" not in catalogo.columns
    assert catalogo["estado_catalogo"].eq("disponible").all()


def test_encabezados_normalizados_no_colisionan(configuracion, muestra):
    """No aceptar dos columnas distintas que terminan con el mismo nombre."""
    muestra["codigo_municipio"] = muestra["Código Municipio"]
    with pytest.raises(ValueError):
        limpiar_divipola(muestra, configuracion)


def test_columna_de_procedencia_reservada_no_se_sobrescribe(configuracion, muestra):
    """La procedencia generada no puede borrar una columna homonima de la entrada."""
    muestra["registro_origen"] = "procedencia externa"
    with pytest.raises(ValueError):
        limpiar_divipola(muestra, configuracion)


def test_columna_nueva_se_conserva_y_reporte_es_json(configuracion, muestra):
    """Conservar campos no tipificados y producir un reporte sin NaN de JSON."""
    muestra["OBSERVACIÓN"] = " texto nuevo "
    catalogo, reporte = limpiar_divipola(muestra, configuracion)
    assert catalogo["observacion"].eq("texto nuevo").all()
    assert str(catalogo["observacion"].dtype) == "string"
    assert "observacion" in reporte["columnas_nuevas_no_tipificadas"]
    # allow_nan=False detecta valores que JSON estandar no puede representar.
    json.dumps(reporte, ensure_ascii=False, allow_nan=False)
