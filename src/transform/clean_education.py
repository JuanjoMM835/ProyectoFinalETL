"""Limpiar educacion segun el contrato, conservando faltantes y trazabilidad."""

import logging
import re
import unicodedata
from typing import Any, Dict, Mapping, Tuple

import pandas as pd


LOGGER = logging.getLogger(__name__)

# Estos campos son identificadores o nombres: no se convierten a numeros.
COLUMNAS_TEXTO = {
    "codigo_municipio", "municipio", "codigo_departamento", "departamento",
    "codigo_etc", "etc",
}

# Declaramos las familias numericas conocidas del MEN. Una columna nueva y
# desconocida se conserva como texto, en lugar de convertirla sin evidencia.
FAMILIAS_TASAS = (
    "cobertura_neta", "cobertura_bruta", "desercion", "aprobacion",
    "reprobacion", "repitencia",
)
NIVELES = ("transicion", "primaria", "secundaria", "media")
COLUMNAS_NUMERICAS = {
    "anio", "poblacion_5_16", "tasa_matriculacion_5_16",
    "tamano_promedio_de_grupo", "sedes_conectadas_a_internet",
}.union(FAMILIAS_TASAS).union(
    "{}_{}".format(familia, nivel)
    for familia in FAMILIAS_TASAS for nivel in NIVELES
)


def normalizar_nombre_columna(nombre: str) -> str:
    """Quitar tildes del encabezado y usar minusculas con guiones bajos."""
    # Los nombres de municipios mantienen sus tildes; solo cambia el encabezado.
    texto = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9]+", "_", texto.strip().lower()).strip("_")
    return "anio" if texto == "ano" else texto


def _normalizar_codigo(serie: pd.Series, longitud: int) -> pd.Series:
    """Completar ceros solo en codigos numericos validos y no nacionales."""
    # Un texto como '50A01' no se transforma en un codigo aparentemente valido.
    valido = serie.str.fullmatch(r"[0-9]{1,%s}" % longitud, na=False)
    valido = valido & ~serie.str.fullmatch(r"0+", na=False)
    return serie.where(valido).str.zfill(longitud)


def _estado_tasa(texto: pd.Series, valores: pd.Series, cobertura: bool) -> pd.Series:
    """Distinguir ausencia, errores de conversion y casos pendientes de revision."""
    estado = pd.Series("disponible", index=valores.index, dtype="string")
    estado.loc[texto.isna()] = "faltante"
    estado.loc[texto.notna() & valores.isna()] = "no_numerico"
    # Infinito es representable por Python, pero no sirve como tasa educativa.
    no_finito = texto.str.lower().isin(["inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"])
    estado.loc[no_finito] = "no_utilizable"
    # Conservamos el valor numerico, pero su estado impide usarlo sin revisar.
    estado.loc[valores.lt(0).fillna(False)] = "no_utilizable"
    superiores = valores.gt(100).fillna(False)
    estado.loc[superiores] = "pendiente_revision" if cobertura else "no_utilizable"
    return estado


def limpiar_educacion(
    datos_originales: pd.DataFrame, configuracion: Mapping[str, Any]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Devolver ``(datos_limpios, reporte)`` sin modificar la tabla recibida.

    Esta etapa prepara educacion en memoria. No guarda Silver, no homologa
    contra DIVIPOLA y no integra todavia poblacion ni internet.
    """
    proceso = configuracion["processing"]
    calidad = configuracion["quality"]
    if proceso["impute_missing_as_zero"] or calidad["clip_education_rates_automatically"]:
        raise ValueError("El contrato no permite imputar ceros ni recortar tasas automaticamente.")
    if not proceso["exclude_national_records"] or not proceso["include_non_municipal_areas"]:
        raise ValueError("La version inicial separa nacionales y conserva areas no municipalizadas.")
    if not calidad["fail_on_missing_key"] or not calidad["fail_on_duplicate_key"]:
        raise ValueError("El contrato exige detenerse ante llaves incompletas o duplicadas.")
    if proceso["primary_key"] != ["codigo_municipio", "anio"]:
        raise ValueError("La llave educativa acordada es codigo_municipio + anio.")

    # Copiar y reiniciar el indice evita cambiar el notebook o confundir indices
    # repetidos con el numero de registro de la fuente.
    datos = datos_originales.copy(deep=True).reset_index(drop=True)
    renombrado = {nombre: normalizar_nombre_columna(nombre) for nombre in datos.columns}
    if len(set(renombrado.values())) != len(renombrado) or datos.columns.duplicated().any():
        raise ValueError("Dos encabezados producen el mismo nombre normalizado.")
    datos = datos.rename(columns=renombrado)
    obligatorias = {
        "anio", "codigo_municipio", "municipio", "codigo_departamento",
        "departamento", "cobertura_neta", "desercion", "reprobacion",
    }
    faltantes = sorted(obligatorias - set(datos.columns))
    if faltantes:
        raise ValueError("Faltan columnas para limpiar educacion: {}".format(faltantes))

    # Guardamos valores relevantes sin limpiar y el ordinal del registro CSV.
    # Este ordinal empieza en 1 y no representa una linea fisica del archivo.
    originales = [
        "anio", "codigo_municipio", "codigo_departamento", "poblacion_5_16",
        "cobertura_neta", "desercion", "reprobacion",
    ]
    reservadas = {
        "registro_origen", "departamento_inconsistente",
        "poblacion_5_16_no_utilizable", "estado_homologacion",
    }.union(
        nombre + "_original" for nombre in originales
    ).union("estado_" + nombre for nombre in ("cobertura_neta", "desercion", "reprobacion"))
    if reservadas.intersection(datos.columns):
        raise ValueError("La fuente utiliza columnas reservadas para trazabilidad.")
    columnas_fuente = list(datos.columns)
    datos["registro_origen"] = pd.Series(range(1, len(datos) + 1), dtype="Int64")
    for nombre in originales:
        if nombre in datos.columns:
            datos[nombre + "_original"] = datos[nombre].astype("string")
    for nombre in columnas_fuente:
        # Un campo con solo espacios pasa a faltante; nunca se rellena con cero.
        datos[nombre] = datos[nombre].astype("string").str.strip().replace("", pd.NA)

    # No dejamos que un anio ilegible desaparezca al filtrar el periodo.
    anios = pd.to_numeric(datos["anio"], errors="coerce")
    anio_invalido = (
        anios.isna() | anios.isin([float("inf"), float("-inf")])
        | anios.le(0) | anios.mod(1).ne(0)
    ).fillna(True)
    if anio_invalido.any():
        raise ValueError("Hay anios incompletos o invalidos en registros: {}".format(
            datos.loc[anio_invalido, "registro_origen"].tolist()[:10]
        ))

    # El codigo nacional debe estar respaldado por su identificacion textual.
    nacional = datos["codigo_municipio"].str.fullmatch(r"0+", na=False)
    departamento_nacional = datos["departamento"].str.upper().isin(["NACIONAL", "COLOMBIA"])
    # Colombia tambien es un municipio de Huila (41206). El nombre aislado
    # nunca basta para separarlo; contrastamos codigo y contexto departamental.
    nombre_nacional = (datos["municipio"].str.upper().eq("NACIONAL") | (
        datos["municipio"].str.upper().eq("COLOMBIA") & departamento_nacional
    )).fillna(False)
    # Un nombre ausente no aporta evidencia nacional. Evitamos que pd.NA
    # deje una contradiccion sin evaluar al comprobarla con .any().
    codigo_departamento_nacional = datos["codigo_departamento"].str.fullmatch(r"0+", na=False)
    if ((nacional != nombre_nacional).any()
            or (nacional & ~departamento_nacional).any()
            or (nacional & ~codigo_departamento_nacional).any()):
        raise ValueError("Codigo y nombre no concuerdan al identificar registros nacionales.")
    inicio, fin = proceso["year_start"], proceso["year_end"]
    if not isinstance(inicio, int) or not isinstance(fin, int) or inicio > fin:
        raise ValueError("El periodo debe tener anios enteros y un inicio no posterior al fin.")
    en_periodo = anios.between(inicio, fin)
    reporte = {
        "filas_entrada": len(datos),
        "registros_nacionales_separados": int(nacional.sum()),
        "registros_territoriales_fuera_periodo": int((~nacional & ~en_periodo).sum()),
        "periodo": {"inicio": inicio, "fin": fin},
        "columnas_renombradas": renombrado,
    }
    datos = datos.loc[~nacional & en_periodo].copy()
    if datos.empty:
        raise ValueError("No hay registros territoriales en el periodo seleccionado.")
    datos["anio"] = anios.loc[datos.index].astype("Int64")

    # Normalizar codigos despues de separar nacionales; DIVIPOLA se revisara
    # en otra etapa. Aqui comprobamos formato, no identidad territorial.
    datos["codigo_municipio"] = _normalizar_codigo(
        datos["codigo_municipio"], proceso["municipality_code_length"]
    )
    datos["codigo_departamento"] = _normalizar_codigo(
        datos["codigo_departamento"], proceso["department_code_length"]
    )
    if datos["codigo_municipio"].isna().any():
        raise ValueError("Hay codigos municipales incompletos o con formato invalido.")
    duplicada = datos.duplicated(proceso["primary_key"], keep=False)
    if duplicada.any():
        ejemplos = datos.loc[duplicada, proceso["primary_key"]].head(10).to_dict("records")
        raise ValueError("Llave municipio-anio duplicada; no se eliminan filas: {}".format(ejemplos))

    # Solo se convierten campos numericos conocidos. Conservamos textos de
    # trabajo para distinguir datos ausentes de conversiones fallidas.
    numericas = sorted((COLUMNAS_NUMERICAS & set(columnas_fuente)) - {"anio"})
    textos = datos[numericas].copy()
    errores_conversion = {}
    correcciones_miles = 0
    correcciones_por_separador = {"coma": 0, "punto": 0}
    for nombre in numericas:
        texto = textos[nombre]
        if nombre == "poblacion_5_16":
            # La fuente 2021 tambien usa puntos: Medellin '379.616'. Solo
            # aceptamos grupos completos de tres digitos en este campo de conteo.
            # '7.74' sigue ambiguo; no adivinamos que significa 7740 habitantes.
            miles_coma = texto.str.fullmatch(r"[0-9]{1,3}(?:,[0-9]{3})+", na=False)
            miles_punto = texto.str.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{3})+", na=False)
            miles = miles_coma | miles_punto
            correcciones_miles = int(miles.sum())
            correcciones_por_separador = {
                "coma": int(miles_coma.sum()), "punto": int(miles_punto.sum())
            }
            sin_separadores = texto.str.replace(",", "", regex=False).str.replace(".", "", regex=False)
            texto = texto.where(~miles, sin_separadores)
        valores = pd.to_numeric(texto, errors="coerce").astype("Float64")
        valores = valores.mask(valores.isin([float("inf"), float("-inf")]))
        errores_conversion[nombre] = int((textos[nombre].notna() & valores.isna()).sum())
        if nombre == "poblacion_5_16":
            # La poblacion escolar es un conteo: no admite fracciones ni negativos.
            invalida = (valores.lt(0) | valores.mod(1).ne(0)).fillna(False)
            datos["poblacion_5_16_no_utilizable"] = (
                invalida | (textos[nombre].notna() & valores.isna())
            )
            valores = valores.mask(invalida)
            datos[nombre] = valores.astype("Int64")
        else:
            # Float64 conserva faltantes y la escala porcentual de la fuente.
            datos[nombre] = valores

    # Las tasas principales conservan su valor y un estado de utilizacion.
    # Cobertura neta >100 queda pendiente; no se recorta a 100 ni se borra.
    for nombre in ("cobertura_neta", "desercion", "reprobacion"):
        datos["estado_" + nombre] = _estado_tasa(
            textos[nombre], datos[nombre], cobertura=(nombre == "cobertura_neta")
        )
    datos["departamento_inconsistente"] = (
        datos["codigo_municipio"].str[:proceso["department_code_length"]]
        .ne(datos["codigo_departamento"]).fillna(True)
    )
    # Tener cinco digitos no prueba la identidad territorial. Esta marca solo
    # cambiara al contrastar con DIVIPOLA o una regla historica respaldada.
    datos["estado_homologacion"] = pd.Series(
        "pendiente_revision", index=datos.index, dtype="string"
    )

    # Separar presencia numerica de utilizacion semantica hace visible el
    # efecto de las coberturas netas >100 pendientes; no declara calidad Gold.
    criticas_educativas = ["cobertura_neta", "desercion", "reprobacion"]
    utilizables = pd.DataFrame({
        nombre: datos["estado_" + nombre].eq("disponible")
        for nombre in criticas_educativas
    })
    presentes = datos[criticas_educativas].notna()

    # El reporte es evidencia de esta fuente; todavia no acredita homologacion
    # del panel ni completitud conjunta con poblacion e internet.
    reporte.update({
        "filas_salida": len(datos),
        "filas_por_anio": {
            str(anio): int(cantidad) for anio, cantidad in datos.groupby("anio").size().items()
        },
        "claves_duplicadas": 0,
        "poblacion_5_16_miles_corregidos": correcciones_miles,
        "poblacion_5_16_miles_por_separador": correcciones_por_separador,
        "conversiones_no_numericas": errores_conversion,
        "departamentos_inconsistentes": int(datos["departamento_inconsistente"].sum()),
        "poblaciones_escolares_no_utilizables": (
            int(datos["poblacion_5_16_no_utilizable"].sum())
            if "poblacion_5_16_no_utilizable" in datos else 0
        ),
        "coberturas_brutas_superiores_100_informativo": (
            int(datos["cobertura_bruta"].gt(100).sum()) if "cobertura_bruta" in datos else 0
        ),
        "completitud_criticas_educativas": {
            nombre: {
                "denominador": len(datos),
                "valores_numericos_presentes": int(presentes[nombre].sum()),
                "valores_utilizables": int(utilizables[nombre].sum()),
                "porcentaje_presencia_numerica": float(presentes[nombre].mean() * 100),
                "porcentaje_utilizables": float(utilizables[nombre].mean() * 100),
            } for nombre in criticas_educativas
        },
        "conjunto_educativo": {
            "denominador": len(datos),
            "filas_con_tres_valores_numericos": int(presentes.all(axis=1).sum()),
            "filas_con_tres_valores_utilizables": int(utilizables.all(axis=1).sum()),
            "porcentaje_presencia_numerica": float(presentes.all(axis=1).mean() * 100),
            "porcentaje_utilizables": float(utilizables.all(axis=1).mean() * 100),
        },
        "columnas_nuevas_no_tipificadas": sorted(
            set(columnas_fuente) - COLUMNAS_NUMERICAS - COLUMNAS_TEXTO
        ),
        "faltantes_por_columna": {
            nombre: int(datos[nombre].isna().sum()) for nombre in columnas_fuente
        },
        "estados_indicadores": {
            nombre: {str(estado): int(cantidad) for estado, cantidad in
                     datos["estado_" + nombre].value_counts().items()}
            for nombre in ("cobertura_neta", "desercion", "reprobacion")
        },
        "valores_numericos_negativos": {
            nombre: int(datos[nombre].lt(0).sum()) for nombre in numericas
        },
        "rangos_numericos": {
            nombre: {
                "min": None if datos[nombre].dropna().empty else float(datos[nombre].min()),
                "max": None if datos[nombre].dropna().empty else float(datos[nombre].max()),
            } for nombre in numericas
        },
    })
    datos = datos.reset_index(drop=True)
    LOGGER.info("Educacion preparada: %s filas territoriales de %s a %s", len(datos), inicio, fin)
    return datos, reporte
