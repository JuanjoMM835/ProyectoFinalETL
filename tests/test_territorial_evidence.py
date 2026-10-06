"""Comprobar evidencia anual selectiva, integridad y preservación de revisiones."""

import copy
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.transform.resolve_territory import (
    aplicar_evidencia_territorial, cargar_evidencia_territorial,
)


@pytest.fixture
def configuracion():
    """Habilitar referencias temporales de prueba sin modificar el YAML real."""
    return {"territorial_evidence": {"enabled": True, "manifest": "data/reference/catalogos_dane.json"},
            "sources": {"population": {"territorial_review_codes": ["27493", "27615", "94343", "94663"]},
                        "internet_access": {"territorial_review_codes": ["27086", "27493"]}}}


def _guardar_json(ruta, contenido):
    """Crear un snapshot de prueba y describir exactamente sus bytes."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"archivo": str(ruta), "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
            "tamano_bytes": ruta.stat().st_size}


def _catalogo(raiz, nombre, atributos, anio=2024, criterio="anio_registro", tipo_capa=None):
    """Guardar features ArcGIS originales y declarar su esquema de forma explícita."""
    archivo = raiz / "data/reference" / nombre
    registro = _guardar_json(archivo, {"features": [{"attributes": fila} for fila in atributos]})
    columnas = {"codigo": "COD", "departamento": "DP", "nombre": "NOM"}
    if criterio == "anio_registro":
        columnas.update(nombre_departamento="DPNOM", tipo="TIP", anio_registro="ANO")
    return dict(registro, anio=anio, criterio_temporal=criterio, columnas=columnas,
                referencia=f"https://geoportal.dane.gov.co/catalogos/{anio}/{nombre}",
                tipo_por_capa=tipo_capa, numero_registros=len(atributos))


def _manifest(raiz, catalogos):
    """Publicar solo el manifiesto de una raíz temporal para que lo lea el loader."""
    _guardar_json(raiz / "data/reference/catalogos_dane.json", {"catalogos_anuales": catalogos})


def _atributo(codigo="05001", departamento="05", nombre="Medellín DANE", anio=2024):
    """Representar atributos oficiales mínimos con año registrado y categoría explícita."""
    return {"COD": codigo, "DP": departamento, "NOM": nombre, "DPNOM": "Antioquia DANE",
            "TIP": "MUNICIPIO", "ANO": anio}


def _normalizado(codigo="05001", departamento="05", nombre="Medellín DANE", tipo="municipio"):
    """Preparar la estructura pública del catálogo ya cargado."""
    return {"codigo_municipio": codigo, "codigo_departamento": departamento,
            "municipio": nombre, "departamento": "Antioquia DANE", "tipo_territorio": tipo}


def _evidencia(registros, anio=2024):
    """Acreditar un solo año: los demás años del mismo código siguen pendientes."""
    return {"vigencia_historica_verificada": False,
            "catalogos_anuales": [{"anio": anio,
                                   "referencia": f"https://geoportal.dane.gov.co/catalogos/{anio}",
                                   "criterio_temporal": "anio_registro", "registros": registros}],
            "codigos_revision_territorial": ["27086", "27493", "27615", "94343", "94663"]}


@pytest.fixture
def panel():
    """Combinar años sin prueba, revisiones históricas y metadatos incompatibles."""
    codigos = ["05001", "05001", "27493", "05002", "05003", "05004", "05005", "05006"]
    cantidad = len(codigos)
    texto = lambda valores: pd.Series(valores, dtype="string")
    booleano = lambda valores: pd.Series(valores, dtype="boolean")
    datos = pd.DataFrame({
        "codigo_municipio": texto(codigos), "anio": pd.Series([2024, 2023] + [2024] * 6, dtype="Int64"),
        "codigo_departamento": texto(["05", "05", "27"] + ["05"] * 5),
        "municipio": texto(["Nombre MEN"] * cantidad), "departamento": texto(["Departamento MEN"] * cantidad),
        "educacion__municipio_original": texto([" Nombre original MEN "] * cantidad),
        "educacion__departamento": texto(["Departamento MEN"] * cantidad),
        "estado_homologacion": texto(["pendiente_revision"] * cantidad),
        "motivo_homologacion": texto(["vigencia_temporal_no_acreditada"] * cantidad),
        "evidencia_homologacion": pd.Series(pd.NA, index=range(cantidad), dtype="string"),
        "fuente_nombre_territorial": texto(["educacion"] * cantidad),
        "tipo_territorio": texto(["no_resuelto"] * cantidad),
        "vigencia_desde": pd.Series(pd.NA, index=range(cantidad), dtype="Int64"),
        "vigencia_hasta": pd.Series(pd.NA, index=range(cantidad), dtype="Int64"),
        "revision_territorial_pendiente": booleano([False] * cantidad),
        "departamento_inconsistente_entre_fuentes": booleano([False] * cantidad),
        "departamento_desconocido_en_coincidencias": booleano([False] * cantidad),
        "coincidencia_poblacion": booleano([True] * cantidad),
        "coincidencia_internet": booleano([True] * 7 + [False]),
        "coincidencia_catalogo_actual": booleano([True] * 6 + [False, True]),
        "estado_catalogo_actual": texto(["disponible"] * 6 + ["sin_coincidencia", "disponible"]),
        "poblacion__codigo_departamento": texto(["05", "05", "27", "05", "08", pd.NA, "05", "05"]),
        "internet__codigo_departamento": texto(["05", "05", "27"] + ["05"] * 4 + [pd.NA]),
        "educacion__metadatos_incompletos": booleano([False, False, False, True] + [False] * 4),
        "poblacion__metadatos_incompletos": booleano([False] * cantidad),
        "internet__metadatos_reporte_pendientes": booleano([False] * 7 + [pd.NA]),
    })
    # Los seis valores pertenecen a sus fuentes; la resolución no los modifica.
    for columna in ["poblacion_total", "poblacion_centros_rural", "accesos_t4"]:
        datos[columna] = pd.Series([100, 100, 0, 100, 100, 100, 100, pd.NA], dtype="Int64")
    for columna in ["cobertura_neta", "desercion", "reprobacion"]:
        datos[columna] = pd.Series([80.0] * cantidad, dtype="Float64")
    datos.attrs = {"origen": {"version": "prueba"}}
    return datos


def test_deshabilitado_no_lee_y_aplicacion_sin_evidencia_preserva_todo(tmp_path, panel):
    """Las pruebas anteriores mantienen su comportamiento si la opción no existe."""
    for cfg in ({}, {"territorial_evidence": {"enabled": False, "manifest": "no_existe.json"}}):
        assert cargar_evidencia_territorial(cfg, tmp_path) == {}
    resultado = aplicar_evidencia_territorial(panel, {})
    assert resultado is not panel
    pd.testing.assert_frame_equal(resultado, panel, check_exact=True)
    resultado.attrs["origen"]["version"] = "otra"
    assert panel.attrs["origen"]["version"] == "prueba"


def test_loader_filtra_anio_registrado_y_conserva_json_original(tmp_path, configuracion):
    """Un servicio con años mezclados solo acredita filas del año declarado."""
    atributos = [_atributo(), _atributo(codigo="05002", anio=2023),
                 _atributo(codigo="05003", anio=None), _atributo(codigo="5004")]
    catalogo = _catalogo(tmp_path, "mixto.json", atributos)
    _manifest(tmp_path, [catalogo])
    bytes_originales = Path(catalogo["archivo"]).read_bytes()
    evidencia = cargar_evidencia_territorial(configuracion, tmp_path)
    cargado = evidencia["catalogos_anuales"][0]
    assert len(cargado["registros"]) == 1
    assert cargado["registros"][0]["codigo_municipio"] == "05001"
    assert cargado["filas_fuera_anio"] == 2 and cargado["filas_invalidas"] == 1
    assert Path(catalogo["archivo"]).read_bytes() == bytes_originales
    assert set(evidencia["codigos_revision_territorial"]) == {"27086", "27493", "27615", "94343", "94663"}
    for entrada in evidencia["entradas_referencia"]:
        archivo = Path(entrada["archivo"])
        assert entrada["sha256"] == hashlib.sha256(archivo.read_bytes()).hexdigest()
        assert entrada["tamano_bytes"] == archivo.stat().st_size


@pytest.mark.parametrize("nombre_general,nombre_anm", [
    ("PACOA (ANM)", "PACOA"), ("PAPUNAUA(ANM)", "PAPUNAUA"),
    ("YAVARATÉ  (ANM)", "YAVARATÉ "),
])
def test_solapamiento_2018_prioriza_anm_sin_borrar_marcador_original(
        tmp_path, configuracion, panel, nombre_general, nombre_anm):
    """La excepción documentada retira solo el marcador categórico al comparar capas."""
    generales = _catalogo(tmp_path, "general.json", [_atributo(nombre=nombre_general)],
                          anio=2018, criterio="capa_anual", tipo_capa=None)
    anm = _catalogo(tmp_path, "anm.json", [_atributo(nombre=nombre_anm)],
                   anio=2018, criterio="capa_anual", tipo_capa="area_no_municipalizada")
    _manifest(tmp_path, [generales, anm])
    evidencia = cargar_evidencia_territorial(configuracion, tmp_path)
    primera = panel.iloc[:1].copy()
    primera["anio"] = pd.Series([2018], dtype="Int64")
    resultado = aplicar_evidencia_territorial(primera, evidencia)
    assert resultado.loc[0, "tipo_territorio"] == "area_no_municipalizada"
    assert resultado.loc[0, "municipio"] == nombre_anm.strip()
    assert resultado.loc[0, "evidencia_homologacion"] == anm["referencia"]
    assert resultado.loc[0, "estado_homologacion"] == "resuelto_catalogo"
    fuente = json.loads(Path(generales["archivo"]).read_text(encoding="utf-8"))
    assert fuente["features"][0]["attributes"]["NOM"] == nombre_general


@pytest.mark.parametrize("problema", ["nombre", "otro_marcador", "sin_prueba_anm", "anio_no_2018", "misma_capa"])
def test_duplicados_conflictivos_no_se_resuelven_por_similitud(tmp_path, configuracion, problema):
    """Nombres parecidos o capas ambiguas no autorizan una identidad anual nueva."""
    anio = 2024 if problema == "anio_no_2018" else 2018
    nombre1 = "PACOA (OTRO)" if problema == "otro_marcador" else "PACOA (ANM)"
    nombre2 = "OTRO TERRITORIO" if problema == "nombre" else "PACOA"
    tipo = None if problema == "sin_prueba_anm" else "area_no_municipalizada"
    general = _catalogo(tmp_path, "general.json", [_atributo(nombre=nombre1)],
                        anio=anio, criterio="capa_anual", tipo_capa=None)
    especifico = _catalogo(tmp_path, "anm.json", [_atributo(nombre=nombre2)],
                           anio=anio, criterio="capa_anual", tipo_capa=tipo)
    if problema == "misma_capa":
        especifico["referencia"] = general["referencia"]
    _manifest(tmp_path, [general, especifico])
    with pytest.raises(ValueError):
        cargar_evidencia_territorial(configuracion, tmp_path)


@pytest.mark.parametrize("problema", ["sha", "tamano", "contenido", "metadata", "fuera_reference",
                                       "anio", "criterio", "dominio", "sin_campo_anio"])
def test_loader_rechaza_integridad_rutas_y_criterios_invalidos(tmp_path, configuracion, problema):
    """La referencia necesita evidencia verificable, no solo una bandera o un nombre de servicio."""
    catalogo = _catalogo(tmp_path, "fuente.json", [_atributo()])
    if problema == "sha":
        catalogo["sha256"] = "0" * 64
    elif problema == "tamano":
        catalogo["tamano_bytes"] += 1
    elif problema == "contenido":
        archivo = Path(catalogo["archivo"])
        archivo.write_text(archivo.read_text(encoding="utf-8").replace("Medellín", "Municipio"), encoding="utf-8")
    elif problema == "metadata":
        catalogo["metadata"] = _guardar_json(tmp_path / "data/reference/meta.json", {"prueba": True})
        catalogo["metadata"]["sha256"] = "0" * 64
    elif problema == "fuera_reference":
        otro = _guardar_json(tmp_path / "data/gold/fuente.json", {"features": []})
        catalogo.update(otro)
    elif problema == "anio":
        catalogo["anio"] = 2017
    elif problema == "criterio":
        catalogo["criterio_temporal"] = "usar_anio_vecino"
    elif problema == "dominio":
        catalogo["referencia"] = "https://otro.example/catalogo"
    else:
        del catalogo["columnas"]["anio_registro"]
    _manifest(tmp_path, [catalogo])
    with pytest.raises(ValueError):
        cargar_evidencia_territorial(configuracion, tmp_path)


def test_resolucion_selectiva_preserva_seis_valores_y_origenes(panel):
    """Solo filas acreditadas sin revisiones ni metadatos incompatibles cambian su identidad."""
    registros = [_normalizado(codigo=codigo, departamento=codigo[:2])
                 for codigo in ["05001", "27493", "05002", "05003", "05004", "05005", "05006"]]
    evidencia = _evidencia(registros)
    originales, evidencia_original = panel.copy(deep=True), copy.deepcopy(evidencia)
    resultado = aplicar_evidencia_territorial(panel, evidencia)
    assert resultado.index.equals(panel.index) and len(resultado) == len(panel)
    assert resultado["estado_homologacion"].eq("resuelto_catalogo").tolist() == [True, False, False, False, False, False, True, True]
    assert resultado.loc[0, "municipio"] == "Medellín DANE"
    assert resultado.loc[0, "departamento"] == "Antioquia DANE"
    assert resultado.loc[0, "fuente_nombre_territorial"] == "catalogo_dane_anual"
    assert resultado.loc[0, "vigencia_desde"] == resultado.loc[0, "vigencia_hasta"] == 2024
    preservadas = ["codigo_municipio", "anio", "codigo_departamento", "educacion__municipio_original",
                  "educacion__departamento", "poblacion_total", "poblacion_centros_rural", "accesos_t4",
                  "cobertura_neta", "desercion", "reprobacion"]
    pd.testing.assert_frame_equal(resultado[preservadas], originales[preservadas], check_exact=True)
    pd.testing.assert_frame_equal(panel, originales, check_exact=True)
    assert evidencia == evidencia_original


@pytest.mark.parametrize("control", ["revision_territorial_pendiente", "departamento_inconsistente_entre_fuentes",
                                    "departamento_desconocido_en_coincidencias", "internet__metadatos_reporte_pendientes"])
@pytest.mark.parametrize("valor", [True, pd.NA])
def test_controles_pendientes_o_desconocidos_impiden_resolver(panel, control, valor):
    """Un metadato desconocido nunca equivale a una comprobación superada."""
    candidata = panel.iloc[:1].copy()
    candidata.loc[0, control] = valor
    resultado = aplicar_evidencia_territorial(candidata, _evidencia([_normalizado()]))
    assert resultado.loc[0, "estado_homologacion"] == "pendiente_revision"


def test_tipo_no_documentado_y_departamento_sin_nombre_conservan_la_limitacion(panel):
    """Acreditar código-año no permite inferir la categoría o un nombre departamental ausente."""
    registro = _normalizado(tipo=None)
    registro["departamento"] = None
    resultado = aplicar_evidencia_territorial(panel.iloc[:1], _evidencia([registro]))
    assert resultado.loc[0, "estado_homologacion"] == "resuelto_catalogo"
    assert resultado.loc[0, "tipo_territorio"] == "no_resuelto"
    assert resultado.loc[0, "departamento"] == "Departamento MEN"


def test_indice_tecnico_repetido_no_propaga_resolucion_a_otro_anio(panel):
    """La fila de 2023 sigue pendiente aunque comparta una etiqueta de índice con 2024."""
    candidata = panel.iloc[:2].copy()
    candidata.index = pd.Index([7, 7], name="indice_tecnico")
    resultado = aplicar_evidencia_territorial(candidata, _evidencia([_normalizado()]))
    assert resultado["estado_homologacion"].tolist() == ["resuelto_catalogo", "pendiente_revision"]
    assert resultado.index.equals(candidata.index)


def test_bandera_global_y_registros_invalidos_no_autorizan_homologacion(panel):
    """Se requiere prueba local válida; el booleano global se rechaza expresamente."""
    with pytest.raises(ValueError):
        aplicar_evidencia_territorial(panel, {"vigencia_historica_verificada": True})
    invalido = _normalizado()
    invalido["municipio"] = None
    resultado = aplicar_evidencia_territorial(panel, _evidencia([invalido]))
    pd.testing.assert_frame_equal(resultado, panel, check_exact=True)
