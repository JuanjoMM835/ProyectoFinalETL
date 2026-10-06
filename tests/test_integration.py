"""Pruebas de integración que protegen el universo MEN, faltantes y procedencia.

Los ejemplos pequeños permiten provocar fallos de unión sin modificar Bronze
ni utilizar los millones de registros del proyecto para cada comprobación.
"""

import copy
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest
import yaml

from src.extract.read_silver import leer_silver
from src.load.export_results import exportar_silver
from src.transform.integrate_sources import integrar_fuentes
from src.transform.quality_silver import construir_reporte_silver


@pytest.fixture
def configuracion():
    """Leer una configuración independiente sin modificar el YAML del proyecto."""
    raiz = Path(__file__).resolve().parents[1]
    return yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))


def _texto(valores):
    """Conservar los códigos y estados como cadenas anulables de pandas."""
    return pd.Series(valores, dtype="string")


@pytest.fixture
def tablas():
    """Crear coincidencias, ausencias y extras que una unión debe distinguir."""
    # Educación define dos filas finales. Las otras fuentes tienen una fila
    # coincidente y otra fuera del universo educativo: no deben crear filas.
    educacion = pd.DataFrame({
        "codigo_municipio": _texto(["05001", "05002"]),
        "anio": pd.Series([2024, 2024], dtype="Int64"),
        "codigo_departamento": _texto(["05", "05"]),
        "municipio": _texto(["Medellín MEN", "Abejorral MEN"]),
        "departamento": _texto(["Antioquia MEN", "Antioquia MEN"]),
        "cobertura_neta": pd.Series([80, 90], dtype="Float64"),
        "desercion": pd.Series([2, 3], dtype="Float64"),
        "reprobacion": pd.Series([0, 1], dtype="Float64"),
        "estado_cobertura_neta": _texto(["disponible"] * 2),
        "estado_desercion": _texto(["disponible"] * 2),
        "estado_reprobacion": _texto(["disponible"] * 2),
        "estado_homologacion": _texto(["pendiente_revision"] * 2),
        "registro_origen": pd.Series([1, 2], dtype="Int64"),
        "municipio_original": _texto([" Medellín MEN ", "Abejorral MEN"]),
    })
    poblacion = pd.DataFrame({
        "codigo_municipio": _texto(["05001", "05003"]),
        "anio": pd.Series([2024, 2024], dtype="Int64"),
        "codigo_departamento": _texto(["05", "05"]),
        "municipio": _texto(["Medellín DANE", "Amagá DANE"]),
        "departamento": _texto(["Antioquia DANE"] * 2),
        "poblacion_total": pd.Series([100, 200], dtype="Int64"),
        "poblacion_cabecera": pd.Series([80, 150], dtype="Int64"),
        "poblacion_centros_rural": pd.Series([20, 50], dtype="Int64"),
        "poblacion_consistente": pd.Series([True, True], dtype="boolean"),
        "estado_poblacion": _texto(["disponible"] * 2),
        "denominador_positivo": pd.Series([True, True], dtype="boolean"),
        "poblacion_para_ratios_utilizable": pd.Series([True, True], dtype="boolean"),
        "estado_homologacion": _texto(["pendiente_revision"] * 2),
    })
    internet = pd.DataFrame({
        "codigo_municipio": _texto(["05001", "05004"]),
        "anio": pd.Series([2024, 2024], dtype="Int64"),
        "codigo_departamento": _texto(["05", "05"]),
        "municipio": _texto(["Medellín CRC", "Municipio exclusivo CRC"]),
        "departamento": _texto(["Antioquia CRC"] * 2),
        "accesos_t4": pd.Series([0, 15], dtype="Int64"),
        "accesos_validos_parcial": pd.Series([0, 15], dtype="Int64"),
        "trimestre_referencia": pd.Series([4, 4], dtype="Int64"),
        "estado_internet": _texto(["disponible"] * 2),
        "accesos_para_indicadores_utilizables": pd.Series([True, True], dtype="boolean"),
        "estado_homologacion": _texto(["pendiente_revision"] * 2),
    })
    divipola = pd.DataFrame({
        "codigo_municipio": _texto(["05001", "05003"]),
        "codigo_departamento": _texto(["05", "05"]),
        "municipio": _texto(["Medellín catálogo", "Amagá catálogo"]),
        "departamento": _texto(["Antioquia catálogo"] * 2),
        "tipo_territorio": _texto(["municipio"] * 2),
        "estado_catalogo": _texto(["disponible"] * 2),
    })
    # La fecha del CSV no prueba vigencia territorial en cada año del panel.
    divipola.attrs["origen_csv"] = {"vigencia_historica_verificada": False}
    return {"educacion": educacion, "poblacion": poblacion,
            "internet": internet, "divipola": divipola}


def test_integracion_preserva_filas_tipos_y_tablas_recibidas(tablas, configuracion):
    """Las uniones no deben borrar, multiplicar filas ni cambiar sus entradas."""
    originales = {nombre: datos.copy(deep=True) for nombre, datos in tablas.items()}
    atributos = {nombre: copy.deepcopy(datos.attrs) for nombre, datos in tablas.items()}
    panel, reporte = integrar_fuentes(tablas, configuracion)
    assert len(panel) == len(tablas["educacion"]) == 2
    assert panel["codigo_municipio"].tolist() == ["05001", "05002"]
    assert not panel.duplicated(["codigo_municipio", "anio"]).any()
    assert isinstance(panel["codigo_municipio"].dtype, pd.StringDtype)
    assert str(panel["anio"].dtype) == "Int64"
    assert str(panel["poblacion_total"].dtype) == "Int64"
    assert str(panel["accesos_t4"].dtype) == "Int64"
    assert str(panel["cobertura_neta"].dtype) == "Float64"
    for nombre, datos in tablas.items():
        pd.testing.assert_frame_equal(datos, originales[nombre], check_exact=True)
        assert datos.attrs == atributos[nombre]
    assert reporte["filas_panel"] == reporte["denominador_panel"] == 2


def test_ausencia_de_fuentes_conserva_faltantes_y_trimestre_ausente(tablas, configuracion):
    """No convertir la ausencia de observaciones en ceros ni en un T4 inventado."""
    panel, _ = integrar_fuentes(tablas, configuracion)
    ausente = panel.loc[panel["codigo_municipio"].eq("05002")].iloc[0]
    assert ausente["estado_poblacion"] == "sin_coincidencia"
    assert ausente["estado_internet"] == "sin_reporte_t4"
    for columna in ["poblacion_total", "poblacion_cabecera", "poblacion_centros_rural",
                    "accesos_t4", "trimestre_referencia"]:
        assert pd.isna(ausente[columna])
    for columna in ["coincidencia_poblacion", "coincidencia_internet", "coincidencia_catalogo_actual"]:
        assert not bool(ausente[columna])
        assert pd.api.types.is_bool_dtype(panel[columna].dtype)
    assert pd.isna(ausente["departamento_coincide_catalogo_actual"])


def test_nombres_men_y_evidencia_de_cada_fuente_no_se_sobrescriben(tablas, configuracion):
    """Un nombre diferente en DANE o CRC no debe reemplazar el universo MEN."""
    panel, _ = integrar_fuentes(tablas, configuracion)
    assert panel["municipio"].tolist() == tablas["educacion"]["municipio"].tolist()
    assert panel["departamento"].tolist() == tablas["educacion"]["departamento"].tolist()
    assert panel["codigo_departamento"].tolist() == ["05", "05"]
    assert panel.loc[0, "poblacion__municipio"] == "Medellín DANE"
    assert panel.loc[0, "internet__municipio"] == "Medellín CRC"
    assert panel.loc[0, "municipio_catalogo_actual"] == "Medellín catálogo"
    assert panel.loc[0, "educacion__municipio_original"] == " Medellín MEN "
    # Los campos de procedencia reciben prefijos para evitar sufijos ambiguos x/y.
    assert panel.loc[0, "educacion__registro_origen"] == 1
    assert not {"municipio_x", "municipio_y"}.intersection(panel.columns)


def test_extras_se_reportan_sin_ampliar_el_universo_educativo(tablas, configuracion):
    """Los registros exclusivos de otras fuentes son diagnóstico, no filas MEN."""
    panel, reporte = integrar_fuentes(tablas, configuracion)
    diagnosticos = reporte["diagnosticos"]
    for fuente, codigo in [("poblacion", "05003"), ("internet", "05004")]:
        control = diagnosticos[fuente]
        assert control["coincidencias"] == control["sin_coincidencia"] == 1
        assert {fila["codigo_municipio"] for fila in control["extras_fuera_universo"]} == {codigo}
        assert codigo not in panel["codigo_municipio"].tolist()
    assert diagnosticos["divipola"]["coincidencias"] == 1
    assert diagnosticos["divipola"]["sin_coincidencia"] == 1
    assert diagnosticos["divipola"]["codigos_catalogo_fuera_universo"] == ["05003"]


def test_coincidencia_actual_no_acredita_vigencia_historica(tablas, configuracion):
    """Un catálogo sin evidencia anual no puede homologar retrospectivamente."""
    panel, reporte = integrar_fuentes(tablas, configuracion)
    assert bool(panel.loc[0, "coincidencia_catalogo_actual"])
    assert bool(panel.loc[0, "departamento_coincide_catalogo_actual"])
    assert panel["estado_homologacion"].eq("pendiente_revision").all()
    homologacion = reporte["homologacion"]
    assert homologacion["numerador_resueltos"] == homologacion["porcentaje"] == 0
    assert homologacion["denominador"] == 2
    assert homologacion["codigos_distintos_pendientes"] == 2
    assert reporte["aceptacion_panel"]["estado"] == "no_cumple"
    assert not reporte["aceptacion_panel"]["cumple_meta"]


def test_completitud_usa_todas_las_filas_y_distingue_aprobacion_temporal(tablas, configuracion):
    """La ausencia de otra fuente permanece en el denominador de dos filas."""
    panel, reporte = integrar_fuentes(tablas, configuracion)
    for columna in configuracion["quality"]["critical_columns"]:
        control = reporte["variables_criticas"][columna]
        esperado = 2 if columna in {"cobertura_neta", "desercion", "reprobacion"} else 1
        assert control["denominador"] == 2
        assert control["numerador_presencia_numerica"] == esperado
        assert control["numerador_utilizables_fuente"] == esperado
        assert control["numerador_utilizables_panel"] == 0
        assert control["porcentaje_utilizables_panel"] == 0
        assert not panel[columna + "_utilizable_panel"].any()
    conjunto = reporte["conjunto_critico"]
    assert conjunto["denominador"] == 2
    assert conjunto["numerador_presencia_numerica"] == 1
    assert conjunto["numerador_utilizables_fuente"] == 1
    assert conjunto["numerador_utilizables_panel"] == 0
    # Serializar estrictamente evita emitir NaN o infinitos en el diagnóstico.
    json.dumps(reporte, ensure_ascii=False, allow_nan=False)


def test_cero_observado_cuenta_y_parcial_no_sustituye_un_total(tablas, configuracion):
    """Distinguir un cero reportado de un total inválido que tiene suma parcial."""
    panel, reporte = integrar_fuentes(tablas, configuracion)
    assert panel.loc[0, "accesos_t4"] == 0
    assert bool(panel.loc[0, "accesos_t4_utilizable_fuente"])
    assert reporte["variables_criticas"]["accesos_t4"]["numerador_presencia_numerica"] == 1
    tablas["internet"].loc[0, "accesos_t4"] = pd.NA
    tablas["internet"].loc[0, "accesos_validos_parcial"] = 999
    tablas["internet"].loc[0, "estado_internet"] = "no_utilizable"
    tablas["internet"].loc[0, "accesos_para_indicadores_utilizables"] = False
    parcial, reporte_parcial = integrar_fuentes(tablas, configuracion)
    assert pd.isna(parcial.loc[0, "accesos_t4"])
    assert parcial.loc[0, "accesos_validos_parcial"] == 999
    assert bool(parcial.loc[0, "coincidencia_internet"])
    assert not bool(parcial.loc[0, "accesos_t4_utilizable_fuente"])
    assert reporte_parcial["variables_criticas"]["accesos_t4"]["numerador_presencia_numerica"] == 0


def test_cero_poblacional_preserva_conteo_pero_no_habilita_division(tablas, configuracion):
    """La completitud de un cero válido no significa que sirva como denominador."""
    for columna in ["poblacion_total", "poblacion_cabecera", "poblacion_centros_rural"]:
        tablas["poblacion"].loc[0, columna] = 0
    tablas["poblacion"].loc[0, "denominador_positivo"] = False
    tablas["poblacion"].loc[0, "poblacion_para_ratios_utilizable"] = False
    panel, reporte = integrar_fuentes(tablas, configuracion)
    assert panel.loc[0, "poblacion_total"] == 0
    assert bool(panel.loc[0, "poblacion_total_utilizable_fuente"])
    assert not bool(panel.loc[0, "poblacion_para_ratios_utilizable"])
    assert reporte["variables_criticas"]["poblacion_total"]["numerador_utilizables_fuente"] == 1


@pytest.mark.parametrize("fuente", ["educacion", "poblacion", "internet", "divipola"])
@pytest.mark.parametrize("problema", ["duplicada", "faltante", "nacional", "corta"])
def test_llaves_invalidas_detienen_integracion(tablas, configuracion, fuente, problema):
    """Ni los extras ni el catálogo pueden introducir duplicados o códigos inválidos."""
    if problema == "duplicada":
        # La duplicidad fuera del universo también invalida la cardinalidad de entrada.
        tablas[fuente] = pd.concat([tablas[fuente], tablas[fuente].iloc[[-1]]], ignore_index=True)
    else:
        tablas[fuente].loc[1, "codigo_municipio"] = {
            "faltante": pd.NA, "nacional": "00000", "corta": "5001",
        }[problema]
    with pytest.raises(ValueError):
        integrar_fuentes(tablas, configuracion)


@pytest.mark.parametrize("fuente", ["educacion", "poblacion", "internet"])
@pytest.mark.parametrize("anio", [2017, 2025, pd.NA])
def test_anios_fuera_del_contrato_o_ausentes_detienen_integracion(tablas, configuracion, fuente, anio):
    """Una Silver anual debe tener años completos dentro de 2018–2024."""
    tablas[fuente].loc[1, "anio"] = anio
    with pytest.raises(ValueError):
        integrar_fuentes(tablas, configuracion)


def test_colisiones_con_el_esquema_final_se_rechazan(tablas, configuracion):
    """No permitir que un campo nuevo suplante un nombre generado de procedencia."""
    tablas["educacion"]["poblacion__municipio"] = _texto(["texto", "texto"])
    with pytest.raises(ValueError):
        integrar_fuentes(tablas, configuracion)


def test_historico_se_conserva_sin_homologacion_por_nombre(tablas, configuracion):
    """Mapiripana no debe convertirse en otro código por parecerse a un nombre."""
    for fuente in ["educacion", "poblacion", "internet"]:
        tablas[fuente].loc[0, "codigo_municipio"] = "94663"
        tablas[fuente].loc[0, "codigo_departamento"] = "94"
        tablas[fuente].loc[0, "municipio"] = "Mapiripana"
    # Un nombre idéntico en el catálogo con código distinto no es correspondencia.
    tablas["divipola"].loc[0, "municipio"] = "Mapiripana"
    panel, _ = integrar_fuentes(tablas, configuracion)
    assert panel.loc[0, "codigo_municipio"] == "94663"
    assert panel.loc[0, "municipio"] == "Mapiripana"
    assert not bool(panel.loc[0, "coincidencia_catalogo_actual"])
    assert panel.loc[0, "estado_homologacion"] == "pendiente_revision"
    assert panel.loc[0, "poblacion_total"] == 100
    assert panel.loc[0, "accesos_t4"] == 0


def test_departamento_contradictorio_se_marca_sin_borrar_valores(tablas, configuracion):
    """La discrepancia territorial debe quedar visible sin reasignar las cifras."""
    tablas["divipola"].loc[0, "codigo_departamento"] = "11"
    panel, _ = integrar_fuentes(tablas, configuracion)
    assert panel.loc[0, "codigo_departamento"] == "05"
    assert not bool(panel.loc[0, "departamento_coincide_catalogo_actual"])
    assert panel.loc[0, "estado_homologacion"] == "pendiente_revision"
    assert panel.loc[0, "poblacion_total"] == 100
    assert panel.loc[0, "accesos_t4"] == 0


def test_departamento_ausente_se_distingue_de_una_contradiccion(tablas, configuracion):
    """Una coincidencia sin departamento tiene identidad desconocida, no diferente."""
    tablas["divipola"].loc[0, "codigo_departamento"] = pd.NA
    panel, reporte = integrar_fuentes(tablas, configuracion)
    assert bool(panel.loc[0, "coincidencia_catalogo_actual"])
    assert pd.isna(panel.loc[0, "departamento_coincide_catalogo_actual"])
    assert bool(panel.loc[0, "departamento_desconocido_en_coincidencias"])
    assert not bool(panel.loc[0, "departamento_inconsistente_entre_fuentes"])
    assert reporte["diagnosticos"]["divipola"]["departamentos_desconocidos"] == 1
    assert reporte["diagnosticos"]["divipola"]["departamentos_incompatibles"] == 0
    assert panel.loc[0, "estado_homologacion"] == "pendiente_revision"
    assert panel.loc[0, "poblacion_total"] == 100


def test_bandera_global_no_puede_acreditar_vigencia_historica(tablas, configuracion):
    """Un booleano sin códigos, años y evidencia no resuelve todas las identidades."""
    with pytest.raises(ValueError):
        integrar_fuentes(tablas, configuracion,
                         evidencia_catalogo={"vigencia_historica_verificada": True})


@pytest.fixture
def silver_publicada(tablas, configuracion, tmp_path):
    """Publicar datos sintéticos y manifiestos válidos en una carpeta temporal."""
    raiz = tmp_path / "proyecto_original"
    raiz.mkdir()
    ejecucion = "silver-integracion-prueba"
    reportes = {nombre: {"filas_salida": len(tabla)} for nombre, tabla in tablas.items()}
    reportes["divipola"]["origen_csv"] = {"vigencia_historica_verificada": False}
    reporte = construir_reporte_silver(tablas, reportes, configuracion, ejecucion)
    metadata = {"etapa": "silver", "estado": "exploratorio", "ejecucion_id": ejecucion,
                "version_contrato": configuracion["project"]["data_contract"]["version"]}
    exportada = exportar_silver(tablas, reporte, metadata, configuracion, raiz)
    return raiz, exportada


def test_lector_verifica_silver_y_preserva_tipos(tablas, configuracion, silver_publicada):
    """La lectura debe recuperar exactamente las cuatro tablas verificadas."""
    raiz, metadata = silver_publicada
    recuperadas, procedencia = leer_silver(configuracion, raiz)
    assert set(recuperadas) == set(tablas)
    for nombre, tabla in tablas.items():
        pd.testing.assert_frame_equal(recuperadas[nombre], tabla, check_exact=True)
    assert procedencia["ejecucion_silver"] == metadata["ejecucion_id"]
    assert procedencia["catalogo_temporal"]["vigencia_historica_verificada"] is False


def test_lector_detecta_cambio_aunque_el_tamano_se_conserve(configuracion, silver_publicada):
    """La huella SHA-256 detecta otra versión sin confiar solo en el tamaño."""
    raiz, metadata = silver_publicada
    ruta = Path(metadata["salidas"]["internet"]["archivo"])
    original = ruta.read_bytes()
    # Solo cambia un byte del archivo temporal de prueba; Bronze sigue intacta.
    ruta.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    assert ruta.stat().st_size == len(original)
    with pytest.raises(ValueError, match="integridad"):
        leer_silver(configuracion, raiz)


def test_lector_rechaza_un_archivo_faltante(configuracion, silver_publicada):
    """Tres Parquet no representan una ejecución de cuatro fuentes completa."""
    raiz, metadata = silver_publicada
    Path(metadata["salidas"]["poblacion"]["archivo"]).unlink()
    with pytest.raises(FileNotFoundError):
        leer_silver(configuracion, raiz)


def test_lector_admite_copia_del_proyecto_con_la_misma_integridad(
        tablas, configuracion, silver_publicada, tmp_path):
    """Las rutas antiguas del manifiesto no obligan a abrir la ubicación anterior."""
    origen, _ = silver_publicada
    trasladada = tmp_path / "proyecto_copiado"
    shutil.copytree(origen, trasladada)
    recuperadas, procedencia = leer_silver(configuracion, trasladada)
    for nombre, tabla in tablas.items():
        pd.testing.assert_frame_equal(recuperadas[nombre], tabla, check_exact=True)
        actual = Path(procedencia["entradas_silver"][nombre]["archivo_actual"])
        assert trasladada.resolve() in actual.parents
    assert procedencia["ejecucion_silver"] == "silver-integracion-prueba"


def test_main_selecciona_integracion_sin_releer_bronze(monkeypatch):
    """El modo --integrar coordina la etapa nueva, sin repetir extracción o Silver."""
    import main as pipeline

    resultado = {"ejecucion_id": "integracion-sintetica"}
    llamadas = []

    def ejecutar_sintetico(ruta):
        """Simular el coordinador sin tocar archivos reales."""
        llamadas.append(("integrar", ruta))
        return resultado

    def mostrar_sintetico(metadata):
        """Verificar que la presentación recibe la ejecución que acaba de terminar."""
        assert metadata is resultado
        llamadas.append(("mostrar", None))

    def etapa_anterior(*args, **kwargs):
        """Fallar si el selector decide volver a extraer Bronze."""
        pytest.fail("--integrar intentó repetir una etapa anterior")

    monkeypatch.setattr(pipeline, "ejecutar_integracion", ejecutar_sintetico)
    monkeypatch.setattr(pipeline, "_mostrar_integracion", mostrar_sintetico)
    for nombre in ["ejecutar_silver", "ejecutar_educacion", "ejecutar_poblacion",
                   "ejecutar_internet", "ejecutar_divipola"]:
        monkeypatch.setattr(pipeline, nombre, etapa_anterior)
    monkeypatch.setattr("sys.argv", ["main.py", "--integrar"])
    pipeline.main()
    assert llamadas == [("integrar", None), ("mostrar", None)]


@pytest.mark.parametrize("otros", [["--silver"], ["--fuente", "internet"]])
def test_main_rechaza_integracion_junto_con_otro_modo(monkeypatch, otros):
    """No ejecutar modos incompatibles al mismo tiempo."""
    import main as pipeline

    monkeypatch.setattr("sys.argv", ["main.py", "--integrar"] + otros)
    with pytest.raises(SystemExit) as error:
        pipeline.main()
    assert error.value.code == 2
