"""Pruebas de reglas que evitan perder o inventar poblacion municipal."""

import copy
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.extract.extract_population import extraer_poblacion
from src.transform.clean_population import limpiar_poblacion


@pytest.fixture
def configuracion():
    """Leer el contrato operativo real sin modificar el archivo YAML."""
    # Cada prueba recibe una configuracion nueva para no contaminar otras pruebas.
    raiz = Path(__file__).resolve().parents[1]
    return yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def muestra():
    """Representar dos territorios y un anio excluido, cada uno con tres areas."""
    # Los codigos cortos permiten verificar que se recuperen los ceros iniciales.
    columnas = ["DP", "DPNOM", "MPIO", "DPMP", "AÑO", "ÁREA GEOGRÁFICA", "TOTAL"]
    filas = [
        ["5", "Antioquia", "5001", " Medellin ", "2024", "Cabecera Municipal", "800"],
        ["5", "Antioquia", "5001", " Medellin ", "2024", "Centros Poblados y Rural Disperso", "200"],
        ["5", "Antioquia", "5001", " Medellin ", "2024", "Total", "1000"],
        ["11", "Bogota", "11001", "Bogota", "2024", "Cabecera Municipal", "900"],
        ["11", "Bogota", "11001", "Bogota", "2024", "Centros Poblados y Rural Disperso", "100"],
        ["11", "Bogota", "11001", "Bogota", "2024", "Total", "1000"],
        ["5", "Antioquia", "5001", "Medellin", "2017", "Cabecera Municipal", "500"],
        ["5", "Antioquia", "5001", "Medellin", "2017", "Centros Poblados y Rural Disperso", "100"],
        ["5", "Antioquia", "5001", "Medellin", "2017", "Total", "600"],
    ]
    return pd.DataFrame(filas, columns=columnas, dtype="string")


def escribir_excel_temporal(ruta, datos, nombre_hoja="PobMunicipalxÁrea"):
    """Crear solamente una fuente de prueba, con el encabezado en la fila ocho."""
    # startrow=7 reproduce header=7 del archivo DANE sin abrir ni escribir Bronze.
    with pd.ExcelWriter(ruta, engine="openpyxl") as libro:
        datos.to_excel(libro, sheet_name=nombre_hoja, startrow=7, index=False)


def test_extractor_conserva_datos_y_archivo(tmp_path, configuracion, muestra):
    """La lectura debe conservar los textos y no sobrescribir el Excel original."""
    ruta = tmp_path / "poblacion.xlsx"
    escribir_excel_temporal(ruta, muestra)
    contenido_original = ruta.read_bytes()
    fuente = copy.deepcopy(configuracion["sources"]["population"])
    fuente["path"] = ruta.name
    extraidos = extraer_poblacion(fuente, tmp_path)
    pd.testing.assert_frame_equal(extraidos, muestra)
    assert ruta.read_bytes() == contenido_original


def test_extractor_detecta_hoja_ausente(tmp_path, configuracion, muestra):
    """No leer por accidente otra hoja si falta la configurada para poblacion."""
    ruta = tmp_path / "otra_hoja.xlsx"
    escribir_excel_temporal(ruta, muestra, nombre_hoja="Otra hoja")
    fuente = copy.deepcopy(configuracion["sources"]["population"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        extraer_poblacion(fuente, tmp_path)


def test_extractor_detecta_columna_ausente(tmp_path, configuracion, muestra):
    """Una fuente sin TOTAL no permite distinguir un dato ausente de una falla."""
    ruta = tmp_path / "incompleta.xlsx"
    escribir_excel_temporal(ruta, muestra.drop(columns="TOTAL"))
    fuente = copy.deepcopy(configuracion["sources"]["population"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        extraer_poblacion(fuente, tmp_path)


def test_extractor_detecta_encabezado_repetido(tmp_path, configuracion, muestra):
    """Detectar la repeticion antes de que pandas la oculte renombrando columnas."""
    ruta = tmp_path / "repetida.xlsx"
    # Conservamos todas las obligatorias: asi el error debe deberse realmente
    # al encabezado duplicado, no a una columna obligatoria que haya desaparecido.
    repetida = pd.concat([muestra, muestra[["DP"]]], axis=1)
    escribir_excel_temporal(ruta, repetida)
    fuente = copy.deepcopy(configuracion["sources"]["population"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        extraer_poblacion(fuente, tmp_path)


def test_limpieza_conserva_entrada_y_crea_una_fila_por_llave(configuracion, muestra):
    """Pasar las tres areas a columnas conservando periodos, codigos y evidencia."""
    original = muestra.copy(deep=True)
    limpia, reporte = limpiar_poblacion(muestra, configuracion)
    pd.testing.assert_frame_equal(muestra, original)
    assert set(limpia["codigo_municipio"]) == {"05001", "11001"}
    assert limpia["anio"].eq(2024).all()
    assert reporte["filas_entrada"] == 9
    assert reporte["filas_datos"] == 9
    assert reporte["filas_fuera_periodo"] == 3
    assert reporte["filas_seleccionadas"] == 6
    assert reporte["filas_salida"] == 2
    assert reporte["claves_duplicadas"] == 0
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    assert medellin["codigo_departamento"] == "05"
    assert medellin["codigo_municipio_original"] == "5001"
    assert medellin["codigo_departamento_original"] == "5"
    assert medellin["poblacion_total"] == 1000
    assert medellin["poblacion_cabecera"] == 800
    assert medellin["poblacion_centros_rural"] == 200
    assert medellin["poblacion_total_original"] == "1000"
    assert medellin["suma_componentes"] == 1000
    assert medellin["diferencia_componentes"] == 0
    assert medellin["poblacion_consistente"]
    assert medellin["estado_poblacion"] == "disponible"
    assert medellin["poblacion_para_ratios_utilizable"]
    assert limpia["estado_homologacion"].eq("pendiente_revision").all()
    for columna in ["anio", "poblacion_total", "poblacion_cabecera", "poblacion_centros_rural"]:
        assert str(limpia[columna].dtype) == "Int64"


def test_procedencia_indica_filas_reales_del_excel(tmp_path, configuracion, muestra):
    """Poder volver a cada celda fuente despues de reorganizar las areas."""
    ruta = tmp_path / "con_procedencia.xlsx"
    escribir_excel_temporal(ruta, muestra)
    fuente = copy.deepcopy(configuracion["sources"]["population"])
    fuente["path"] = ruta.name
    extraidos = extraer_poblacion(fuente, tmp_path)
    limpia, _ = limpiar_poblacion(extraidos, configuracion)
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    # Excel cuenta desde uno: encabezado fila 8 y primeras observaciones 9, 10 y 11.
    assert medellin["fila_excel_cabecera"] == 9
    assert medellin["fila_excel_centros_rural"] == 10
    assert medellin["fila_excel_total"] == 11


def test_notas_y_filas_vacias_se_separan_sin_perder_evidencia(configuracion, muestra):
    """Las notas no son territorios; se reportan y no se mezclan con la tabla."""
    notas = pd.DataFrame([
        [None, None, None, None, None, None, None],
        ["Fuente: DANE", None, None, None, None, None, None],
        ["Nota: valores de prueba", None, None, None, None, None, None],
    ], columns=muestra.columns, dtype="string")
    entrada = pd.concat([muestra, notas], ignore_index=True)
    limpia, reporte = limpiar_poblacion(entrada, configuracion)
    assert len(limpia) == 2
    assert reporte["filas_entrada"] == 12
    assert reporte["filas_datos"] == 9
    assert reporte["filas_vacias"] == 1
    assert len(reporte["notas_archivo"]) == 2
    assert {nota["texto"] for nota in reporte["notas_archivo"]} == {
        "Fuente: DANE", "Nota: valores de prueba",
    }
    assert all(nota["fila_excel"] > 0 for nota in reporte["notas_archivo"])


def test_fila_territorial_incompleta_no_se_confunde_con_nota(configuracion, muestra):
    """Una fila con DP numerico no debe descartarse como pie de pagina."""
    incompleta = pd.DataFrame([["5", None, None, None, None, None, None]],
                              columns=muestra.columns, dtype="string")
    with pytest.raises(ValueError):
        limpiar_poblacion(pd.concat([muestra, incompleta], ignore_index=True), configuracion)


def test_duplicado_tras_normalizar_detiene_proceso(configuracion, muestra):
    """Dos valores para la misma area no se deben sumar ni elegir arbitrariamente."""
    duplicada = muestra.iloc[[0]].copy()
    duplicada["MPIO"] = "05001"
    duplicada["TOTAL"] = "900"
    entrada = pd.concat([muestra, duplicada], ignore_index=True)
    with pytest.raises(ValueError):
        limpiar_poblacion(entrada, configuracion)


@pytest.mark.parametrize("codigo", [None, "", "50A01", "050001", "0"])
def test_codigo_municipal_invalido_no_desaparece(configuracion, muestra, codigo):
    """Detenerse ante una llave municipal ausente o imposible de normalizar."""
    muestra.loc[0, "MPIO"] = codigo
    with pytest.raises(ValueError):
        limpiar_poblacion(muestra, configuracion)


@pytest.mark.parametrize("anio", [None, "texto", "2024.5", "inf"])
def test_anio_invalido_se_detecta_antes_del_filtro(configuracion, muestra, anio):
    """No contar un anio ilegible como si fuera un anio fuera del periodo."""
    muestra.loc[6, "AÑO"] = anio
    with pytest.raises(ValueError):
        limpiar_poblacion(muestra, configuracion)


@pytest.mark.parametrize("columna,valor", [("DPMP", "Otro municipio"), ("DPNOM", "Otro departamento")])
def test_metadatos_contradictorios_entre_areas_detienen_proceso(configuracion, muestra, columna, valor):
    """Una misma llave no puede tomar el nombre de la primera area silenciosamente."""
    muestra.loc[1, columna] = valor
    with pytest.raises(ValueError):
        limpiar_poblacion(muestra, configuracion)


def test_departamento_invalido_se_preserva_para_revision(configuracion, muestra):
    """Conservar poblacion y municipio aunque el codigo departamental requiera revision."""
    muestra.loc[:2, "DP"] = "XX"
    limpia, _ = limpiar_poblacion(muestra, configuracion)
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    assert pd.isna(medellin["codigo_departamento"])
    assert medellin["codigo_departamento_original"] == "XX"
    assert medellin["departamento_inconsistente"]
    assert medellin["poblacion_total"] == 1000
    assert medellin["estado_poblacion"] == "pendiente_revision"
    assert not medellin["poblacion_para_ratios_utilizable"]


@pytest.mark.parametrize("area", ["Rural sin clasificar", None])
def test_categoria_invalida_no_desaparece_al_pivotar(configuracion, muestra, area):
    """Una categoria nueva o vacia requiere revision antes de reorganizar la tabla."""
    # No permitimos que reindex descarte una categoria desconocida de la fuente.
    muestra.loc[1, "ÁREA GEOGRÁFICA"] = area
    with pytest.raises(ValueError, match="categorias de area"):
        limpiar_poblacion(muestra, configuracion)


def test_area_ausente_en_toda_la_fuente_no_se_imputa(configuracion, muestra):
    """Crear la columna rural incluso cuando ninguna fila trae esa area."""
    entrada = muestra.loc[muestra["ÁREA GEOGRÁFICA"] != "Centros Poblados y Rural Disperso"].copy()
    limpia, reporte = limpiar_poblacion(entrada, configuracion)
    assert limpia["poblacion_centros_rural"].isna().all()
    assert limpia["fila_excel_centros_rural"].isna().all()
    assert limpia["areas_incompletas"].all()
    assert limpia["poblacion_consistente"].isna().all()
    assert limpia["estado_poblacion"].eq("no_utilizable").all()
    assert reporte["areas_incompletas"] == 2


def test_total_ausente_no_se_infiere_de_los_componentes(configuracion, muestra):
    """Una suma comprobable no reemplaza el dato Total que falta en la fuente."""
    entrada = muestra.loc[muestra["ÁREA GEOGRÁFICA"] != "Total"].copy()
    limpia, _ = limpiar_poblacion(entrada, configuracion)
    assert limpia["poblacion_total"].isna().all()
    assert limpia["suma_componentes"].eq(1000).all()
    assert limpia["diferencia_componentes"].isna().all()
    assert limpia["poblacion_consistente"].isna().all()
    assert not limpia["poblacion_para_ratios_utilizable"].any()


@pytest.mark.parametrize("valor", ["texto", "-1", "12.5", "inf", "NaN"])
def test_conteo_invalido_conserva_original_y_no_es_utilizable(configuracion, muestra, valor):
    """No convertir errores, negativos o fracciones en un conteo valido."""
    muestra.loc[2, "TOTAL"] = valor
    limpia, _ = limpiar_poblacion(muestra, configuracion)
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    assert pd.isna(medellin["poblacion_total"])
    assert medellin["poblacion_total_original"] == valor
    assert medellin["estado_poblacion"] == "no_utilizable"
    assert pd.isna(medellin["poblacion_consistente"])
    assert not medellin["poblacion_para_ratios_utilizable"]


def test_conteo_ausente_permanece_ausente(configuracion, muestra):
    """Un registro de area presente con dato vacio tampoco permite usar su poblacion."""
    muestra.loc[1, "TOTAL"] = pd.NA
    limpia, _ = limpiar_poblacion(muestra, configuracion)
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    assert pd.isna(medellin["poblacion_centros_rural"])
    assert pd.isna(medellin["suma_componentes"])
    assert pd.isna(medellin["poblacion_consistente"])
    assert medellin["estado_poblacion"] == "no_utilizable"
    assert not medellin["poblacion_para_ratios_utilizable"]


def test_total_inconsistente_se_preserva_y_se_bloquea(configuracion, muestra):
    """Registrar la diferencia sin recalcular Total ni ajustar los componentes."""
    muestra.loc[2, "TOTAL"] = "1001"
    limpia, reporte = limpiar_poblacion(muestra, configuracion)
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    assert medellin["poblacion_total"] == 1001
    assert medellin["suma_componentes"] == 1000
    assert abs(medellin["diferencia_componentes"]) == 1
    assert not medellin["poblacion_consistente"]
    assert medellin["estado_poblacion"] == "no_utilizable"
    assert not medellin["poblacion_para_ratios_utilizable"]
    assert reporte["componentes_inconsistentes"] == 1


def test_poblacion_cero_es_un_dato_valido_pero_no_un_denominador(configuracion, muestra):
    """Distinguir el cero observado de un faltante y evitar divisiones por cero."""
    muestra.loc[:2, "TOTAL"] = "0"
    limpia, reporte = limpiar_poblacion(muestra, configuracion)
    medellin = limpia.set_index("codigo_municipio").loc["05001"]
    assert medellin["poblacion_total"] == 0
    assert medellin["poblacion_cabecera"] == 0
    assert medellin["poblacion_centros_rural"] == 0
    assert medellin["poblacion_consistente"]
    assert medellin["estado_poblacion"] == "disponible"
    assert not medellin["denominador_positivo"]
    assert not medellin["poblacion_para_ratios_utilizable"]
    assert reporte["poblacion_total_cero"] == 1


@pytest.mark.parametrize("codigo,departamento", [("27493", "27"), ("27615", "27"),
                                                  ("94343", "94"), ("94663", "94")])
def test_codigo_con_revision_territorial_se_preserva(configuracion, muestra, codigo, departamento):
    """Conservar cifras historicas sin dar por resuelta su correspondencia territorial."""
    muestra.loc[:2, "MPIO"] = codigo
    muestra.loc[:2, "DP"] = departamento
    muestra.loc[:2, "DPMP"] = "Territorio de prueba"
    muestra.loc[:2, "DPNOM"] = "Departamento de prueba"
    limpia, _ = limpiar_poblacion(muestra, configuracion)
    territorio = limpia.set_index("codigo_municipio").loc[codigo]
    assert territorio["poblacion_total"] == 1000
    assert territorio["revision_territorial_pendiente"]
    assert territorio["estado_poblacion"] == "pendiente_revision"
    assert not territorio["poblacion_para_ratios_utilizable"]


def test_reporte_es_json_y_estado_consistencia_es_nullable(configuracion, muestra):
    """Guardar el reporte sin NaN JSON y distinguir desconocido de False."""
    muestra.loc[1, "TOTAL"] = pd.NA
    limpia, reporte = limpiar_poblacion(muestra, configuracion)
    assert str(limpia["poblacion_consistente"].dtype) == "boolean"
    # allow_nan=False impide reportes con valores que no pertenecen al estandar JSON.
    json.dumps(reporte, ensure_ascii=False, allow_nan=False)
