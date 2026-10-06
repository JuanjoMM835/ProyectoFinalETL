"""Comprobar indicadores territoriales sin inventar datos, años ni denominadores.

Las cuatro filas sintéticas se entregan desordenadas para comprobar que el
crecimiento busca el año anterior por llave y conserva el orden de entrada.
"""

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.transform.build_indicators import construir_indicadores


NOMBRES = (
    "accesos_por_100_habitantes", "porcentaje_centros_rural", "crecimiento_anual_accesos",
)


@pytest.fixture
def configuracion():
    """Leer las reglas del contrato sin modificar la configuración real."""
    raiz = Path(__file__).resolve().parents[1]
    return yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def panel():
    """Representar datos completos y una identidad acreditada solo para la prueba."""
    # El municipio 05001 tiene años consecutivos; 05002 solo tiene 2024.
    # La acreditación es sintética: no homologa registros reales del proyecto.
    datos = pd.DataFrame({
        "codigo_municipio": pd.Series(["05001", "05002", "05001", "05001"], dtype="string"),
        "anio": pd.Series([2020, 2024, 2018, 2019], dtype="Int64"),
        "poblacion_total": pd.Series([100, 80, 100, 100], dtype="Int64"),
        "poblacion_cabecera": pd.Series([80, 40, 80, 80], dtype="Int64"),
        "poblacion_centros_rural": pd.Series([20, 40, 20, 20], dtype="Int64"),
        "accesos_t4": pd.Series([0, 4, 10, 20], dtype="Int64"),
        "trimestre_referencia": pd.Series([4] * 4, dtype="Int64"),
        "estado_poblacion": pd.Series(["disponible"] * 4, dtype="string"),
        "estado_internet": pd.Series(["disponible"] * 4, dtype="string"),
        "estado_homologacion": pd.Series(["resuelto_catalogo"] * 4, dtype="string"),
        "poblacion_consistente": pd.Series([True] * 4, dtype="boolean"),
        "poblacion_total_utilizable_fuente": pd.Series([True] * 4, dtype="boolean"),
        "poblacion_centros_rural_utilizable_fuente": pd.Series([True] * 4, dtype="boolean"),
        "accesos_t4_utilizable_fuente": pd.Series([True] * 4, dtype="boolean"),
        "municipio": pd.Series(["Medellín", "Abejorral", "Medellín", "Medellín"], dtype="string"),
    })
    return datos


def test_formulas_conservan_filas_orden_tipos_y_entrada(panel, configuracion):
    """Comparar fórmulas y estados sin ordenar ni cambiar el panel recibido."""
    original = panel.copy(deep=True)
    datos, reporte = construir_indicadores(panel, configuracion)
    pd.testing.assert_frame_equal(panel, original, check_exact=True)
    pd.testing.assert_frame_equal(datos[original.columns], original, check_exact=True)
    esperados = {
        "accesos_por_100_habitantes": [0, 5, 10, 20],
        "porcentaje_centros_rural": [20, 50, 20, 20],
        "crecimiento_anual_accesos": [-100, pd.NA, pd.NA, 100],
    }
    for nombre, valores in esperados.items():
        pd.testing.assert_series_equal(datos[nombre], pd.Series(valores, dtype="Float64", name=nombre))
        assert str(datos[nombre + "_diagnostico"].dtype) == "Float64"
        for columna in ["estado_" + nombre, "motivo_" + nombre,
                        "estado_" + nombre + "_diagnostico", "motivo_" + nombre + "_diagnostico"]:
            assert isinstance(datos[columna].dtype, pd.StringDtype)
    assert reporte["etapa"] == "indicadores"
    assert reporte["filas_panel"] == reporte["denominador_panel"] == 4
    json.dumps(reporte, ensure_ascii=False, allow_nan=False)


def test_crecimiento_no_salta_anios_y_2018_no_aplica(panel, configuracion):
    """Un valor de 2020 no puede compararse con 2018 cuando falta 2019."""
    panel = panel.loc[panel["anio"].ne(2019)].reset_index(drop=True)
    datos, reporte = construir_indicadores(panel, configuracion)
    base = datos.loc[datos["anio"].eq(2018)].iloc[0]
    assert base["estado_crecimiento_anual_accesos"] == "no_aplica"
    assert base["motivo_crecimiento_anual_accesos"] == "sin_anio_previo_en_alcance"
    sin_previo = datos.loc[datos["anio"].eq(2020)].iloc[0]
    assert pd.isna(sin_previo["crecimiento_anual_accesos"])
    assert pd.isna(sin_previo["crecimiento_anual_accesos_diagnostico"])
    assert sin_previo["estado_crecimiento_anual_accesos"] != "disponible"
    assert reporte["indicadores"]["crecimiento_anual_accesos"]["denominador"] == 3


def test_crecimiento_anterior_cero_no_produce_infinito(panel, configuracion):
    """El cero actual permite -100 %, pero un cero previo no permite dividir."""
    panel.loc[panel["anio"].eq(2018), "accesos_t4"] = 0
    datos, _ = construir_indicadores(panel, configuracion)
    actual_2019 = datos.loc[datos["anio"].eq(2019)].iloc[0]
    assert pd.isna(actual_2019["crecimiento_anual_accesos"])
    assert pd.isna(actual_2019["crecimiento_anual_accesos_diagnostico"])
    actual_2020 = datos.loc[datos["anio"].eq(2020)].iloc[0]
    assert actual_2020["crecimiento_anual_accesos"] == -100


def test_homologacion_pendiente_separa_diagnostico_de_indicador(panel, configuracion):
    """Conservar el candidato calculable sin presentarlo como cifra validada."""
    panel["estado_homologacion"] = pd.Series(["pendiente_revision"] * len(panel), dtype="string")
    datos, reporte = construir_indicadores(panel, configuracion)
    for nombre in NOMBRES:
        assert datos[nombre].isna().all()
        control = reporte["indicadores"][nombre]
        assert control["denominador"] == 4
        assert control["numerador_calculables"] == 0
        assert control["pct_calculables"] == 0
    assert datos["accesos_por_100_habitantes_diagnostico"].tolist() == [0, 5, 10, 20]
    assert datos["porcentaje_centros_rural_diagnostico"].tolist() == [20, 50, 20, 20]
    assert reporte["indicadores"]["crecimiento_anual_accesos"]["numerador_diagnostico"] == 2


def test_crecimiento_exige_homologacion_en_ambos_anios(panel, configuracion):
    """Resolver solo el año actual no acredita la identidad de la observación previa."""
    panel.loc[panel["anio"].eq(2018), "estado_homologacion"] = "pendiente_revision"
    datos, _ = construir_indicadores(panel, configuracion)
    actual = datos.loc[datos["anio"].eq(2019)].iloc[0]
    assert pd.isna(actual["crecimiento_anual_accesos"])
    assert actual["crecimiento_anual_accesos_diagnostico"] == 100
    # La razón del año actual depende solo de la identidad y datos de ese año.
    assert actual["accesos_por_100_habitantes"] == 20


@pytest.mark.parametrize("problema", ["estado", "bandera", "trimestre", "negativo"])
def test_crecimiento_revalida_la_fuente_del_anio_previo(panel, configuracion, problema):
    """Los datos actuales no sustituyen la disponibilidad y calidad del año anterior."""
    previo = panel["anio"].eq(2018)
    if problema == "estado":
        panel.loc[previo, "estado_internet"] = "sin_reporte_t4"
    elif problema == "bandera":
        panel.loc[previo, "accesos_t4_utilizable_fuente"] = False
    elif problema == "trimestre":
        panel.loc[previo, "trimestre_referencia"] = 3
    else:
        panel.loc[previo, "accesos_t4"] = -1
    datos, _ = construir_indicadores(panel, configuracion)
    actual = datos.loc[datos["anio"].eq(2019)].iloc[0]
    assert pd.isna(actual["crecimiento_anual_accesos"])
    assert pd.isna(actual["crecimiento_anual_accesos_diagnostico"])
    assert actual["accesos_por_100_habitantes"] == 20


@pytest.mark.parametrize("problema", ["cero", "negativo", "faltante", "componentes"])
def test_poblacion_invalida_no_se_usa_aunque_las_banderas_digan_true(panel, configuracion, problema):
    """Recomprobar total, signo y componentes, sin confiar ciegamente en banderas."""
    if problema == "cero":
        panel.loc[0, ["poblacion_total", "poblacion_cabecera", "poblacion_centros_rural"]] = 0
    elif problema == "negativo":
        panel.loc[0, "poblacion_total"] = -100
    elif problema == "faltante":
        panel.loc[0, "poblacion_total"] = pd.NA
    else:
        panel.loc[0, "poblacion_cabecera"] = 90
    datos, _ = construir_indicadores(panel, configuracion)
    for nombre in ["accesos_por_100_habitantes", "porcentaje_centros_rural"]:
        assert pd.isna(datos.loc[0, nombre])
        assert pd.isna(datos.loc[0, nombre + "_diagnostico"])
    assert datos.loc[0, "poblacion_consistente"] == True


@pytest.mark.parametrize("problema", ["negativo", "faltante", "trimestre", "bandera", "estado"])
def test_internet_no_utilizable_no_se_convierte_en_accesos(panel, configuracion, problema):
    """El acceso observado necesita signo válido, T4 y controles de fuente."""
    if problema == "negativo":
        panel.loc[0, "accesos_t4"] = -1
    elif problema == "faltante":
        panel.loc[0, "accesos_t4"] = pd.NA
        panel["accesos_validos_parcial"] = pd.Series([999] * 4, dtype="Int64")
    elif problema == "trimestre":
        panel.loc[0, "trimestre_referencia"] = 3
    elif problema == "bandera":
        panel.loc[0, "accesos_t4_utilizable_fuente"] = False
    else:
        panel.loc[0, "estado_internet"] = "pendiente_revision"
    datos, _ = construir_indicadores(panel, configuracion)
    for nombre in ["accesos_por_100_habitantes", "crecimiento_anual_accesos"]:
        assert pd.isna(datos.loc[0, nombre])
        assert pd.isna(datos.loc[0, nombre + "_diagnostico"])
    assert datos.loc[0, "porcentaje_centros_rural"] == 20


def test_reporte_mantiene_denominador_completo_y_diferencia_ausencias(panel, configuracion):
    """Los no aplicables y faltantes siguen dentro del panel para reportar su cálculo."""
    datos, reporte = construir_indicadores(panel, configuracion)
    for nombre in NOMBRES:
        control = reporte["indicadores"][nombre]
        assert control["denominador"] == len(panel)
        esperado = 2 if nombre == "crecimiento_anual_accesos" else 4
        assert control["numerador_calculables"] == control["numerador_diagnostico"] == esperado
        assert control["pct_calculables"] == control["pct_diagnostico"] == esperado / 4 * 100
    assert len(datos) == 4


def test_tasa_educativa_pendiente_no_bloquea_variables_independientes(panel, configuracion):
    """Los tres indicadores nuevos no requieren cobertura neta ni deserción."""
    panel["cobertura_neta"] = pd.Series([105] * 4, dtype="Float64")
    panel["estado_cobertura_neta"] = pd.Series(["pendiente_revision"] * 4, dtype="string")
    panel["cobertura_neta_utilizable_fuente"] = pd.Series([False] * 4, dtype="boolean")
    datos, _ = construir_indicadores(panel, configuracion)
    assert datos["accesos_por_100_habitantes"].notna().all()
    assert datos["porcentaje_centros_rural"].notna().all()
    assert datos["crecimiento_anual_accesos"].notna().sum() == 2
    assert datos["cobertura_neta"].eq(105).all()


@pytest.mark.parametrize("bandera", ["departamento_inconsistente_entre_fuentes",
                                     "departamento_desconocido_en_coincidencias"])
def test_identidad_departamental_inconsistente_o_desconocida_no_habilita_diagnostico(
        panel, configuracion, bandera):
    """Un cruce territorial dudoso no debe presentar siquiera el candidato como apto."""
    panel[bandera] = pd.Series([True, False, False, False], dtype="boolean")
    datos, _ = construir_indicadores(panel, configuracion)
    for nombre in NOMBRES:
        assert pd.isna(datos.loc[0, nombre])
        assert pd.isna(datos.loc[0, nombre + "_diagnostico"])


def test_enteros_grandes_no_desbordan_componentes_o_multiplicacion(panel, configuracion):
    """Hacer sumas de conteos con enteros exactos antes de calcular porcentajes."""
    maximo = 2 ** 63 - 1
    panel.loc[0, "poblacion_total"] = maximo
    panel.loc[0, "poblacion_cabecera"] = maximo - 1
    panel.loc[0, "poblacion_centros_rural"] = 1
    panel.loc[0, "accesos_t4"] = maximo
    datos, _ = construir_indicadores(panel, configuracion)
    assert datos.loc[0, "accesos_por_100_habitantes"] == pytest.approx(100)
    assert datos.loc[0, "porcentaje_centros_rural"] == pytest.approx(100 / maximo)
    assert datos.loc[0, "porcentaje_centros_rural"] > 0


@pytest.mark.parametrize("problema", ["duplicada", "codigo", "anio", "tipo"])
def test_esquema_o_llave_invalida_detiene_indicadores(panel, configuracion, problema):
    """Una tabla con llave o tipos inválidos no puede recibir indicadores nuevos."""
    if problema == "duplicada":
        panel = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    elif problema == "codigo":
        panel.loc[0, "codigo_municipio"] = "00000"
    elif problema == "anio":
        panel.loc[0, "anio"] = 2025
    else:
        panel["accesos_t4"] = panel["accesos_t4"].astype("string")
    with pytest.raises(ValueError):
        construir_indicadores(panel, configuracion)
