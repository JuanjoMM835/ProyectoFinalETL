"""Pruebas para sumar accesos T4 sin perder faltantes ni duplicar reportes de la CRC."""

import copy
import json
from contextlib import closing
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.extract.extract_internet import extraer_internet
from src.transform.clean_internet import limpiar_internet


COLUMNAS = [
    "ANNO", "TRIMESTRE", "ID_EMPRESA", "EMPRESA", "ID_MUNICIPIO",
    "MUNICIPIO", "ID_DEPARTAMENTO", "DEPARTAMENTO", "ID_SEGMENTO",
    "SEGMENTO", "VELOCIDAD_EFECTIVA_DOWNSTREAM",
    "VELOCIDAD_EFECTIVA_UPSTREAM", "ID_TECNOLOGIA", "TECNOLOGIA", "ACCESOS",
]


@pytest.fixture
def configuracion():
    """Leer las reglas reales y aislar las opciones de cada prueba."""
    # Las pruebas cambian su copia, nunca el YAML guardado ni los datos Bronze.
    raiz = Path(__file__).resolve().parents[1]
    reglas = yaml.safe_load((raiz / "config" / "config.yaml").read_text(encoding="utf-8"))
    fuente = reglas["sources"]["internet_access"]
    fuente["required_columns"] = COLUMNAS.copy()
    fuente["review_segment_ids"] = ["117"]
    fuente["territorial_review_codes"] = ["27086", "27493", "27615", "94343", "94663"]
    return reglas


def fila(**cambios):
    """Construir un reporte sintetico con una llave detallada valida."""
    # Cada llamada crea una fila independiente para expresar solo el caso probado.
    registro = {
        "ANNO": "2018", "TRIMESTRE": "4", "ID_EMPRESA": "900123456",
        "EMPRESA": "Proveedor de prueba", "ID_MUNICIPIO": "5001",
        "MUNICIPIO": "Medellín", "ID_DEPARTAMENTO": "5", "DEPARTAMENTO": "Antioquia",
        "ID_SEGMENTO": "101", "SEGMENTO": "Residencial estrato 1",
        "VELOCIDAD_EFECTIVA_DOWNSTREAM": "20", "VELOCIDAD_EFECTIVA_UPSTREAM": "5",
        "ID_TECNOLOGIA": "101", "TECNOLOGIA": "DSL", "ACCESOS": "10",
    }
    registro.update(cambios)
    return registro


def tabla(*registros):
    """Mantener los quince campos de la fuente como texto, incluso los codigos."""
    return pd.DataFrame(registros, columns=COLUMNAS, dtype="string")


@pytest.fixture
def muestra():
    """Incluir dos reportes T4, un trimestre distinto, un cero y un anio excluido."""
    return tabla(
        fila(),
        fila(ID_TECNOLOGIA="102", TECNOLOGIA="Cable", ACCESOS="20"),
        fila(TRIMESTRE="3", ACCESOS="900"),
        fila(ANNO="2024", ID_MUNICIPIO="11001", MUNICIPIO="Bogotá, D.C.",
             ID_DEPARTAMENTO="11", DEPARTAMENTO="Bogotá, D.C.", ACCESOS="0"),
        fila(ANNO="2025", ACCESOS="500"),
    )


def bloques(datos, tamano=2):
    """Simular lectura incremental sin modificar ni compartir vistas de la entrada."""
    for inicio in range(0, len(datos), tamano):
        yield datos.iloc[inicio:inicio + tamano].copy(deep=True)


def leer_bloques(fuente, raiz):
    """Cerrar el lector aunque una prueba falle antes de consumir todo el archivo."""
    with closing(extraer_internet(fuente, raiz)) as lector:
        return list(lector)


def test_extractor_lee_bloques_y_conserva_archivo(tmp_path, configuracion, muestra):
    """Leer incrementalmente conserva textos, ceros iniciales y el CSV original."""
    ruta = tmp_path / "internet.csv"
    muestra.to_csv(ruta, sep=";", index=False, encoding="utf-8")
    original = ruta.read_bytes()
    fuente = copy.deepcopy(configuracion["sources"]["internet_access"])
    fuente["path"] = ruta.name
    fuente["read_options"]["chunksize"] = 2
    partes = leer_bloques(fuente, tmp_path)
    assert [len(parte) for parte in partes] == [2, 2, 1]
    pd.testing.assert_frame_equal(pd.concat(partes, ignore_index=True), muestra)
    assert ruta.read_bytes() == original


@pytest.mark.parametrize("columna", ["ID_EMPRESA", "EMPRESA", "ID_SEGMENTO", "SEGMENTO", "ACCESOS"])
def test_extractor_exige_campos_para_llave_y_suma(tmp_path, configuracion, muestra, columna):
    """No agregar reportes cuya identidad o medida requerida este ausente."""
    ruta = tmp_path / "incompleto.csv"
    muestra.drop(columns=columna).to_csv(ruta, sep=";", index=False, encoding="utf-8")
    fuente = copy.deepcopy(configuracion["sources"]["internet_access"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        leer_bloques(fuente, tmp_path)


def test_extractor_detecta_encabezado_repetido(tmp_path, configuracion, muestra):
    """Detectar encabezados duplicados antes de que pandas los renombre."""
    ruta = tmp_path / "repetido.csv"
    pd.concat([muestra, muestra[["ACCESOS"]]], axis=1).to_csv(
        ruta, sep=";", index=False, encoding="utf-8")
    fuente = copy.deepcopy(configuracion["sources"]["internet_access"])
    fuente["path"] = ruta.name
    with pytest.raises(ValueError):
        leer_bloques(fuente, tmp_path)


def test_literal_na_de_tecnologia_sigue_siendo_texto(tmp_path, configuracion):
    """NA es una etiqueta observada de tecnologia, no un dato faltante de pandas."""
    datos = tabla(fila(ID_TECNOLOGIA="0", TECNOLOGIA="NA", ACCESOS="7"))
    ruta = tmp_path / "tecnologia_na.csv"
    datos.to_csv(ruta, sep=";", index=False, encoding="utf-8")
    fuente = copy.deepcopy(configuracion["sources"]["internet_access"])
    fuente["path"] = ruta.name
    partes = leer_bloques(fuente, tmp_path)
    assert partes[0].loc[0, "TECNOLOGIA"] == "NA"
    resultado, reporte = limpiar_internet(iter(partes), configuracion)
    assert resultado.loc[0, "accesos_t4"] == 7
    assert reporte["tecnologia_na_global"] == 1
    assert reporte["tecnologia_na_seleccionada"] == 1


def test_t4_se_suma_entre_bloques_sin_modificar_entrada(configuracion, muestra):
    """Dos tecnologias aportan 30 accesos, sin sumar el T3 ni el anio 2025."""
    original = muestra.copy(deep=True)
    resultado, reporte = limpiar_internet(bloques(muestra, tamano=1), configuracion)
    pd.testing.assert_frame_equal(muestra, original)
    medellin = resultado.loc[resultado["codigo_municipio"].eq("05001")].iloc[0]
    assert medellin["anio"] == 2018
    assert medellin["codigo_departamento"] == "05"
    assert medellin["accesos_t4"] == 30
    assert medellin["registros_fuente"] == 2
    assert medellin["registros_accesos_no_utilizables"] == 0
    assert medellin["accesos_validos_parcial"] == 30
    assert medellin["trimestre_referencia"] == 4
    assert medellin["estado_internet"] == "disponible"
    assert medellin["estado_homologacion"] == "pendiente_revision"
    assert reporte["filas_entrada"] == 5
    assert reporte["bloques_leidos"] == 5
    assert reporte["filas_fuera_periodo"] == 1
    assert reporte["filas_otros_trimestres_periodo"] == 1
    assert reporte["filas_seleccionadas"] == 3
    assert reporte["filas_salida"] == 2
    assert reporte["claves_duplicadas"] == 0
    assert str(resultado["codigo_municipio"].dtype) == "string"
    assert str(resultado["accesos_t4"].dtype) == "Int64"
    assert resultado["accesos_para_indicadores_utilizables"].all()


def test_cero_reportado_se_conserva_como_observacion(configuracion):
    """Un cero presente aporta informacion y no debe convertirse en faltante."""
    resultado, _ = limpiar_internet([tabla(fila(ACCESOS="0"))], configuracion)
    assert resultado.loc[0, "accesos_t4"] == 0
    assert resultado.loc[0, "accesos_validos_parcial"] == 0
    assert resultado.loc[0, "estado_internet"] == "disponible"
    assert bool(resultado.loc[0, "accesos_para_indicadores_utilizables"])


def test_sin_t4_no_se_inventa_una_fila_anual(configuracion):
    """Conservar ausencia de T4 sin sustituir por T3 ni generar accesos cero."""
    resultado, reporte = limpiar_internet([tabla(fila(TRIMESTRE="3", ACCESOS="50"))], configuracion)
    assert resultado.empty
    assert {"codigo_municipio", "anio", "accesos_t4", "estado_internet"}.issubset(resultado.columns)
    assert str(resultado["accesos_t4"].dtype) == "Int64"
    assert reporte["filas_seleccionadas"] == reporte["filas_salida"] == 0
    json.dumps(reporte, allow_nan=False)


@pytest.mark.parametrize("valor", ["", "texto", "-1", "1.5", "inf"])
def test_un_acceso_invalido_impide_publicar_total_incompleto(configuracion, valor):
    """Una suma parcial puede diagnosticar, pero no representar el total anual."""
    datos = tabla(fila(ACCESOS="10"), fila(ID_EMPRESA="900999111", ACCESOS=valor))
    resultado, _ = limpiar_internet(bloques(datos, 1), configuracion)
    assert pd.isna(resultado.loc[0, "accesos_t4"])
    assert resultado.loc[0, "accesos_validos_parcial"] == 10
    assert resultado.loc[0, "registros_fuente"] == 2
    assert resultado.loc[0, "registros_accesos_no_utilizables"] == 1
    assert resultado.loc[0, "estado_internet"] == "no_utilizable"
    assert not bool(resultado.loc[0, "accesos_para_indicadores_utilizables"])


def test_todos_los_accesos_invalidos_no_producen_parcial_cero(configuracion):
    """Pandas no debe transformar una suma de faltantes en un cero observado."""
    resultado, _ = limpiar_internet([tabla(fila(ACCESOS=""))], configuracion)
    assert pd.isna(resultado.loc[0, "accesos_t4"])
    assert pd.isna(resultado.loc[0, "accesos_validos_parcial"])


@pytest.mark.parametrize("accesos", ["10", "999"])
def test_reporte_repetido_entre_bloques_es_error_aunque_cambie_medida(configuracion, accesos):
    """ACCESOS no forma parte de la identidad: cambiarlo no crea otro reporte."""
    datos = tabla(fila(), fila(ACCESOS=accesos))
    with pytest.raises(ValueError):
        limpiar_internet(bloques(datos, 1), configuracion)


def test_variaciones_de_nombres_no_ocultan_duplicados(configuracion):
    """Los nombres descriptivos no reemplazan los identificadores de la llave."""
    datos = tabla(fila(), fila(EMPRESA="Otro nombre", MUNICIPIO=" MEDELLIN ",
                               SEGMENTO="Otro texto", TECNOLOGIA="otra etiqueta"))
    with pytest.raises(ValueError):
        limpiar_internet([datos], configuracion)


@pytest.mark.parametrize("equivalente", ["2.0", "2,0", "02.00"])
def test_velocidades_equivalentes_no_evaden_unicidad(configuracion, equivalente):
    """Dos representaciones del mismo decimal deben compartir una llave canonica."""
    datos = tabla(fila(VELOCIDAD_EFECTIVA_DOWNSTREAM="2"),
                  fila(VELOCIDAD_EFECTIVA_DOWNSTREAM=equivalente))
    with pytest.raises(ValueError):
        limpiar_internet(bloques(datos, 1), configuracion)


@pytest.mark.parametrize("cambios", [{"ANNO": "2025"}, {"TRIMESTRE": "3"}])
def test_unicidad_tambien_se_verifica_fuera_de_seleccion(configuracion, cambios):
    """No esconder repeticiones del archivo porque caen fuera del periodo o T4."""
    datos = tabla(fila(**cambios), fila(**cambios))
    with pytest.raises(ValueError):
        limpiar_internet(bloques(datos, 1), configuracion)


@pytest.mark.parametrize("campo,valor", [
    ("ANNO", ""), ("ANNO", "texto"), ("ANNO", "2024.5"),
    ("TRIMESTRE", ""), ("TRIMESTRE", "0"), ("TRIMESTRE", "5"), ("TRIMESTRE", "4.5"),
])
def test_periodos_invalidos_se_detectan_antes_del_filtro(configuracion, campo, valor):
    """Un periodo desconocido no permite decidir con seguridad si debe excluirse."""
    datos = tabla(fila(ANNO="2025"))
    datos.loc[0, campo] = valor
    with pytest.raises(ValueError):
        limpiar_internet([datos], configuracion)


@pytest.mark.parametrize("codigo", ["", "abc", "123456", "0"])
def test_codigo_municipal_invalido_no_se_descarta_en_silencio(configuracion, codigo):
    """Un cero municipal solo es nacional si el resto del contexto lo confirma."""
    with pytest.raises(ValueError):
        limpiar_internet([tabla(fila(ID_MUNICIPIO=codigo))], configuracion)


@pytest.mark.parametrize("campo,valor", [
    ("ID_EMPRESA", ""), ("ID_EMPRESA", "empresa-x"),
    ("ID_SEGMENTO", ""), ("ID_SEGMENTO", "101.5"),
    ("ID_TECNOLOGIA", ""), ("ID_TECNOLOGIA", "tecnologia-x"),
])
def test_identificadores_detallados_invalidos_son_error(configuracion, campo, valor):
    """Sin IDs validos no es posible comprobar la identidad de cada reporte."""
    with pytest.raises(ValueError):
        limpiar_internet([tabla(fila(**{campo: valor}))], configuracion)


def test_nacionales_se_separan_y_colombia_huila_se_conserva(configuracion):
    """El municipio Colombia no debe confundirse con reportes de todo el pais."""
    datos = tabla(
        fila(ID_MUNICIPIO="0", MUNICIPIO="COLOMBIA", ID_DEPARTAMENTO="0", DEPARTAMENTO="COLOMBIA"),
        fila(TRIMESTRE="3", ID_MUNICIPIO="0", MUNICIPIO="NACIONAL", ID_DEPARTAMENTO="0", DEPARTAMENTO="NACIONAL"),
        fila(ID_MUNICIPIO="41206", MUNICIPIO="Colombia", ID_DEPARTAMENTO="41", DEPARTAMENTO="Huila", ACCESOS="8"),
    )
    resultado, reporte = limpiar_internet(bloques(datos, 1), configuracion)
    assert resultado["codigo_municipio"].tolist() == ["41206"]
    assert resultado.loc[0, "accesos_t4"] == 8
    assert reporte["filas_nacionales_globales"] == 2
    assert reporte["filas_nacionales_t4_separados"] == 1


@pytest.mark.parametrize("segmento", ["117", "999"])
def test_segmento_pendiente_conserva_accesos_sin_autorizar_indicador(configuracion, segmento):
    """Una categoria por revisar no desaparece de la suma ni se da por aprobada."""
    resultado, _ = limpiar_internet([tabla(fila(ID_SEGMENTO=segmento, SEGMENTO="Categoria por revisar"))], configuracion)
    assert resultado.loc[0, "accesos_t4"] == 10
    assert bool(resultado.loc[0, "segmento_pendiente_revision"])
    assert resultado.loc[0, "estado_internet"] == "pendiente_revision"
    assert not bool(resultado.loc[0, "accesos_para_indicadores_utilizables"])


def test_revision_territorial_no_reasigna_codigo_ni_accesos(configuracion):
    """Mapiripana conserva codigo y medida mientras su historia esta pendiente."""
    resultado, _ = limpiar_internet([tabla(fila(ID_MUNICIPIO="94663", MUNICIPIO="Mapiripana",
                                              ID_DEPARTAMENTO="94", DEPARTAMENTO="Guainía"))], configuracion)
    assert resultado.loc[0, "codigo_municipio"] == "94663"
    assert resultado.loc[0, "accesos_t4"] == 10
    assert bool(resultado.loc[0, "revision_territorial_pendiente"])
    assert resultado.loc[0, "estado_internet"] == "pendiente_revision"


def test_departamento_inconsistente_no_se_corrige_por_suposicion(configuracion):
    """Un prefijo distinto marca revision y conserva el total observado."""
    resultado, _ = limpiar_internet([tabla(fila(ID_DEPARTAMENTO="41", DEPARTAMENTO="Huila"))], configuracion)
    assert resultado.loc[0, "codigo_municipio"] == "05001"
    assert resultado.loc[0, "accesos_t4"] == 10
    assert bool(resultado.loc[0, "departamento_inconsistente"])
    assert resultado.loc[0, "estado_internet"] == "pendiente_revision"


@pytest.mark.parametrize("campo", ["SEGMENTO", "TECNOLOGIA"])
def test_total_agregado_en_categoria_es_error_por_riesgo_de_doble_suma(configuracion, campo):
    """No sumar simultaneamente detalle y una categoria que declara ser el total."""
    with pytest.raises(ValueError):
        limpiar_internet([tabla(fila(**{campo: "TOTAL"}))], configuracion)


def test_velocidad_negativa_no_crea_metricas_inventadas(configuracion):
    """Los accesos observados se mantienen, pero una velocidad invalida marca revision."""
    resultado, _ = limpiar_internet([tabla(fila(VELOCIDAD_EFECTIVA_DOWNSTREAM="-5"))], configuracion)
    assert resultado.loc[0, "accesos_t4"] == 10
    assert bool(resultado.loc[0, "metadatos_reporte_pendientes"])
    assert resultado.loc[0, "estado_internet"] == "pendiente_revision"
    assert not any("velocidad" in columna or "fibra" in columna for columna in resultado.columns)


def test_reporte_se_serializa_sin_nan_y_explicita_estados(configuracion, muestra):
    """El reporte debe poder guardarse como JSON estricto para una futura carga."""
    resultado, reporte = limpiar_internet(bloques(muestra), configuracion)
    serializado = json.dumps(reporte, ensure_ascii=False, allow_nan=False)
    assert json.loads(serializado)["filas_salida"] == len(resultado)
    assert reporte["estados_internet"] == {"disponible": 2}
    assert "filas_por_anio" in reporte
    assert "resumen_anual_accesos" in reporte


@pytest.mark.parametrize("valor", ["2.0000000000000001", "9007199254740992.1"])
def test_fraccion_minima_no_se_redondea_a_un_acceso_entero(configuracion, valor):
    """El texto exacto revela fracciones que un float podria convertir en enteros."""
    # Los accesos representan conteos: una fraccion sigue invalida aunque sea minima.
    datos = tabla(fila(ACCESOS="7"), fila(ID_EMPRESA="900999111", ACCESOS=valor))
    resultado, _ = limpiar_internet(bloques(datos, 1), configuracion)
    assert pd.isna(resultado.loc[0, "accesos_t4"])
    assert resultado.loc[0, "accesos_validos_parcial"] == 7
    assert resultado.loc[0, "registros_accesos_no_utilizables"] == 1
    assert resultado.loc[0, "estado_internet"] == "no_utilizable"


def test_entero_grande_en_texto_decimal_preserva_precision(configuracion):
    """El decimal .0 debe conservar todos los digitos de un entero mayor que 2**53."""
    # Esta cifra permite detectar la perdida de una unidad si se convierte mediante float.
    esperado = 9007199254740993
    resultado, _ = limpiar_internet([tabla(fila(ACCESOS="9007199254740993.0"))], configuracion)
    assert resultado.loc[0, "accesos_t4"] == esperado
    assert resultado.loc[0, "accesos_validos_parcial"] == esperado
    assert str(resultado["accesos_t4"].dtype) == "Int64"


def test_entero_grande_no_pierde_precision_al_compartir_columna_con_invalido(configuracion):
    """Un faltante generado en la conversion no debe forzar numeros intermedios float."""
    # Una contribucion invalida bloquea el total, pero el diagnostico conserva el entero exacto.
    datos = tabla(fila(ACCESOS="9007199254740993.0"),
                  fila(ID_EMPRESA="900999111", ACCESOS="texto"))
    resultado, _ = limpiar_internet([datos], configuracion)
    assert pd.isna(resultado.loc[0, "accesos_t4"])
    assert resultado.loc[0, "accesos_validos_parcial"] == 9007199254740993
    assert resultado.loc[0, "registros_accesos_no_utilizables"] == 1


def test_maximo_int64_es_conteo_valido(configuracion):
    """El limite incluido del tipo Int64 puede almacenarse sin desbordamiento."""
    # Construir el limite como entero de Python evita aproximaciones al generar la fuente.
    limite = 2 ** 63 - 1
    resultado, reporte = limpiar_internet([tabla(fila(ACCESOS=str(limite)))], configuracion)
    assert resultado.loc[0, "accesos_t4"] == limite
    assert resultado.loc[0, "accesos_validos_parcial"] == limite
    assert resultado.loc[0, "estado_internet"] == "disponible"
    assert reporte["resumen_anual_accesos"][0]["accesos"] == limite


def test_suma_anual_de_varios_municipios_usa_enteros_sin_desbordamiento(configuracion):
    """Una suma diagnostica anual puede superar Int64 sin alterar cada fila municipal."""
    limite = 2 ** 63 - 1
    datos = tabla(fila(ACCESOS=str(limite)),
                  fila(ID_MUNICIPIO="05002", MUNICIPIO="Abejorral", ACCESOS=str(limite)))
    resultado, reporte = limpiar_internet(bloques(datos, 1), configuracion)
    assert len(resultado) == 2
    assert resultado["accesos_t4"].eq(limite).all()
    # La suma del reporte usa enteros de Python, no una suma vectorial que pueda desbordarse.
    assert reporte["resumen_anual_accesos"][0]["accesos"] == 18446744073709551614
    reconstruido = json.loads(json.dumps(reporte, allow_nan=False))
    assert reconstruido["resumen_anual_accesos"][0]["accesos"] == 18446744073709551614


def test_suma_municipal_fuera_de_int64_detiene_el_proceso(configuracion):
    """Una fila que excede su tipo declarado no debe envolver ni truncar el conteo."""
    limite = 2 ** 63 - 1
    datos = tabla(fila(ACCESOS=str(limite)),
                  fila(ID_EMPRESA="900999111", ACCESOS=str(limite)))
    # Son dos reportes distintos del mismo municipio; el error es la suma, no la llave.
    with pytest.raises(ValueError):
        limpiar_internet(bloques(datos, 1), configuracion)


@pytest.mark.parametrize("campo,valor", [
    ("ANNO", "2024.0000000000000001"),
    ("TRIMESTRE", "4.0000000000000001"),
])
def test_periodo_con_fraccion_minima_no_se_redondea(configuracion, campo, valor):
    """Un decimal casi entero no identifica exactamente un anio o un trimestre."""
    # Comparar el texto exacto impide seleccionar por error una fraccion como T4 de 2024.
    with pytest.raises(ValueError):
        limpiar_internet([tabla(fila(**{campo: valor}))], configuracion)


def test_main_selecciona_internet_sin_recorrer_csv(monkeypatch, capsys):
    """El argumento de terminal debe coordinar la fuente elegida y su presentacion."""
    import main as pipeline

    datos = pd.DataFrame({"prueba": ["solo en memoria"]})
    reporte = {"prueba": "sin leer Bronze"}
    llamadas = []

    def ejecutar_sintetico(ruta_configuracion):
        """Sustituir la lectura real por objetos identificables en la prueba."""
        llamadas.append(("ejecutar", ruta_configuracion))
        return datos, reporte

    def mostrar_sintetico(tabla_recibida, reporte_recibido):
        """Comprobar que main entrega exactamente el resultado del ejecutor."""
        assert tabla_recibida is datos
        assert reporte_recibido is reporte
        llamadas.append(("mostrar", None))

    def fuente_no_seleccionada(*args, **kwargs):
        """Una ruta accidental hacia otra fuente debe fallar claramente."""
        pytest.fail("La opcion internet intento ejecutar otra fuente")

    # Reemplazamos las cuatro entradas: una seleccion incorrecta tampoco leera otros CSV.
    monkeypatch.setattr(pipeline, "ejecutar_internet", ejecutar_sintetico)
    monkeypatch.setattr(pipeline, "_mostrar_internet", mostrar_sintetico)
    for nombre in ["ejecutar_educacion", "ejecutar_poblacion", "ejecutar_divipola"]:
        monkeypatch.setattr(pipeline, nombre, fuente_no_seleccionada)
    monkeypatch.setattr("sys.argv", ["main.py", "--fuente", "internet"])
    pipeline.main()
    assert llamadas == [("ejecutar", None), ("mostrar", None)]
    assert "Resultado en memoria" in capsys.readouterr().out
