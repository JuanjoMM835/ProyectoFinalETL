"""Preparar poblacion municipal anual y comprobar sus componentes."""

import copy
import logging
import re
from typing import Any, Dict, Mapping, Tuple

import pandas as pd


LOGGER = logging.getLogger(__name__)

# Cada fila original representa UNA categoria, no un total que debamos sumar.
AREAS = {
    "Total": "total",
    "Cabecera Municipal": "cabecera",
    "Centros Poblados y Rural Disperso": "centros_rural",
}
RENOMBRADO = {
    "DP": "codigo_departamento", "DPNOM": "departamento",
    "MPIO": "codigo_municipio", "DPMP": "municipio", "AÑO": "anio",
    "ÁREA GEOGRÁFICA": "area_geografica", "TOTAL": "poblacion",
}


def _normalizar_codigo(serie: pd.Series, longitud: int) -> pd.Series:
    """Completar ceros en identificadores numericos validos, conservando texto."""
    valido = serie.str.fullmatch(r"[0-9]{1,%s}" % longitud, na=False)
    valido = valido & ~serie.str.fullmatch(r"0+", na=False)
    return serie.where(valido).str.zfill(longitud)


def limpiar_poblacion(
    datos_originales: pd.DataFrame, configuracion: Mapping[str, Any]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Devolver ``(tabla_anual, reporte)`` en memoria, sin escribir Silver.

    La tabla conserva todos los territorios DANE del periodo. El universo MEN
    se aplicara durante la integracion, no mediante un filtro en esta limpieza.
    """
    proceso = configuracion["processing"]
    calidad = configuracion["quality"]
    fuente = configuracion["sources"]["population"]
    if proceso["impute_missing_as_zero"]:
        raise ValueError("El contrato no permite imputar ceros en poblacion.")
    if not proceso["include_non_municipal_areas"]:
        raise ValueError("La primera version conserva areas no municipalizadas.")
    if not calidad["fail_on_missing_key"] or not calidad["fail_on_duplicate_key"]:
        raise ValueError("La llave incompleta o duplicada debe detener esta etapa.")
    if not calidad["require_population_components_consistency"] or not calidad["require_positive_population_for_ratios"]:
        raise ValueError("Se requiere controlar componentes y denominadores positivos.")
    if proceso["primary_key"] != ["codigo_municipio", "anio"]:
        raise ValueError("La llave acordada es codigo_municipio + anio.")
    inicio, fin = proceso["year_start"], proceso["year_end"]
    if type(inicio) is not int or type(fin) is not int or inicio > fin:
        raise ValueError("El periodo debe tener anios enteros en orden valido.")

    # Los casos ya identificados en el contrato se declaran en YAML. Esta lista
    # solo marca revision: no sustituye codigos ni redistribuye habitantes.
    codigos_revision = fuente.get("territorial_review_codes", [])
    longitud = proceso["municipality_code_length"]
    if not isinstance(codigos_revision, list) or any(
        not isinstance(codigo, str)
        or re.fullmatch(r"[0-9]{%s}" % longitud, codigo) is None
        or re.fullmatch(r"0+", codigo) is not None
        for codigo in codigos_revision
    ):
        raise ValueError("Los codigos de revision territorial deben ser textos validos.")

    # Trabajamos con una copia y preservamos los valores antes de quitar espacios.
    datos = datos_originales.copy(deep=True).reset_index(drop=True)
    if datos.columns.duplicated().any():
        raise ValueError("La fuente repite encabezados de poblacion.")
    faltantes = sorted(set(RENOMBRADO) - set(datos.columns))
    if faltantes:
        raise ValueError("Faltan columnas para limpiar poblacion: {}".format(faltantes))
    nuevas = sorted(set(datos.columns) - set(RENOMBRADO))
    if nuevas:
        raise ValueError("Se requieren reglas para columnas nuevas de poblacion: {}".format(nuevas))
    datos = datos.rename(columns=RENOMBRADO)
    origen = copy.deepcopy(datos_originales.attrs.get("origen_excel", {}))
    encabezado = origen.get("header", fuente["read_options"]["header"])
    # +2: pasar del indice de header a la primera fila de datos visible en Excel.
    datos["fila_excel"] = pd.Series(
        range(encabezado + 2, encabezado + 2 + len(datos)), dtype="Int64"
    )
    for nombre in ("codigo_municipio", "codigo_departamento", "poblacion"):
        datos[nombre + "_original"] = datos[nombre].astype("string")
    for nombre in RENOMBRADO.values():
        datos[nombre] = datos[nombre].astype("string").str.strip().replace("", pd.NA)

    # Una nota reconocida ocupa solo DP. Una fila con codigo DP y el resto
    # vacio es un registro incompleto y debe fallar, no desaparecer como nota.
    campos = list(RENOMBRADO.values())
    vacias = datos[campos].isna().all(axis=1)
    solo_dp = datos[[nombre for nombre in campos if nombre != "codigo_departamento"]].isna().all(axis=1)
    notas = solo_dp & datos["codigo_departamento"].str.match(
        r"(?i)^(fuente\s*:|nota\s*:|actualizado\b)", na=False
    )
    notas_archivo = [
        {"fila_excel": int(fila), "texto": texto}
        for fila, texto in datos.loc[notas, ["fila_excel", "codigo_departamento"]]
        .itertuples(index=False, name=None)
    ]
    reporte = {
        "filas_entrada": len(datos), "filas_vacias": int(vacias.sum()),
        "notas_archivo": notas_archivo, "origen_excel": origen,
        "periodo": {"inicio": inicio, "fin": fin}, "columnas_renombradas": RENOMBRADO.copy(),
    }
    datos = datos.loc[~vacias & ~notas].copy()
    reporte["filas_datos"] = len(datos)

    # Validar antes de filtrar evita esconder un anio ilegible como fuera de rango.
    anios = pd.to_numeric(datos["anio"], errors="coerce")
    anio_invalido = (
        anios.isna() | anios.isin([float("inf"), float("-inf")])
        | anios.le(0) | anios.mod(1).ne(0)
    ).fillna(True)
    if anio_invalido.any():
        raise ValueError("Hay anios incompletos o invalidos en filas Excel: {}".format(
            datos.loc[anio_invalido, "fila_excel"].tolist()[:10]
        ))
    en_periodo = anios.between(inicio, fin)
    reporte["filas_fuera_periodo"] = int((~en_periodo).sum())
    datos = datos.loc[en_periodo].copy()
    if datos.empty:
        raise ValueError("No hay registros de poblacion en el periodo seleccionado.")
    datos["anio"] = anios.loc[datos.index].astype("Int64")
    datos["codigo_municipio"] = _normalizar_codigo(datos["codigo_municipio"], longitud)
    datos["codigo_departamento"] = _normalizar_codigo(
        datos["codigo_departamento"], proceso["department_code_length"]
    )
    if datos["codigo_municipio"].isna().any():
        raise ValueError("Hay codigos municipales incompletos o con formato invalido.")
    if not datos["area_geografica"].isin(AREAS).all():
        raise ValueError("Hay categorias de area incompletas o no reconocidas.")
    llaves = proceso["primary_key"]
    duplicadas = datos.duplicated(llaves + ["area_geografica"], keep=False)
    if duplicadas.any():
        raise ValueError("Llave municipio-anio-area duplicada; no se suman ni eliminan filas.")

    # Los nombres y el departamento deben concordar entre las areas del mismo
    # territorio-anio. Comprobarlo permite tomar sus metadatos sin elegir entre
    # dos identidades contradictorias ni multiplicar filas al unirlas.
    columnas_metadata = ["codigo_departamento", "municipio", "departamento"]
    grupos = datos.groupby(llaves, sort=True)
    contradictorias = grupos[columnas_metadata].nunique(dropna=False).gt(1)
    if contradictorias.any().any():
        raise ValueError("Hay metadatos contradictorios entre areas del mismo municipio-anio.")

    # TOTAL es un conteo de personas de ESTA area. No eliminamos separadores
    # como en el CSV educativo: el Excel real ya contiene numeros enteros.
    valores = pd.to_numeric(datos["poblacion"], errors="coerce").astype("Float64")
    no_finito = valores.isin([float("inf"), float("-inf")])
    finitos = valores.mask(no_finito)
    negativos = finitos.lt(0).fillna(False)
    fraccionarios = finitos.mod(1).ne(0).fillna(False)
    errores_conversion = datos["poblacion"].notna() & valores.isna()
    valores = valores.mask(no_finito | negativos | fraccionarios)
    datos["poblacion"] = valores.astype("Int64")

    # pivot exige una observacion por llave-area. A diferencia de pivot_table,
    # no aplica una suma o promedio que pueda ocultar un duplicado de la fuente.
    tabla = datos.pivot(index=llaves, columns="area_geografica", values="poblacion")
    tabla = tabla.reindex(columns=list(AREAS)).rename(
        columns={area: "poblacion_" + sufijo for area, sufijo in AREAS.items()}
    ).astype("Int64")
    # Reindex conserva una columna faltante incluso si el area no aparece en
    # ningun registro. Un componente ausente nunca se completa con cero.
    for campo, prefijo in (("poblacion_original", "poblacion_"), ("fila_excel", "fila_excel_")):
        auxiliar = datos.pivot(index=llaves, columns="area_geografica", values=campo)
        auxiliar = auxiliar.reindex(columns=list(AREAS)).rename(columns={
            area: prefijo + sufijo + ("_original" if campo == "poblacion_original" else "")
            for area, sufijo in AREAS.items()
        })
        auxiliar = auxiliar.astype("string" if campo == "poblacion_original" else "Int64")
        tabla = tabla.join(auxiliar, validate="one_to_one")
    tabla = tabla.join(grupos[columnas_metadata].first(), validate="one_to_one")
    # Estos dos originales proceden de la fila Total. Las tres filas fisicas
    # permiten consultar tambien los codigos originales de cada componente.
    originales_total = datos.loc[datos["area_geografica"].eq("Total")].set_index(llaves)[
        ["codigo_municipio_original", "codigo_departamento_original"]
    ]
    tabla = tabla.join(originales_total, validate="one_to_one").reset_index()
    tabla.columns.name = None

    poblaciones = ["poblacion_" + sufijo for sufijo in AREAS.values()]
    filas_origen = ["fila_excel_" + sufijo for sufijo in AREAS.values()]
    tabla["areas_incompletas"] = tabla[filas_origen].isna().any(axis=1)
    completas = tabla[poblaciones].notna().all(axis=1)
    # La suma propaga NA: tener solo cabecera no permite inventar el total.
    tabla["suma_componentes"] = tabla["poblacion_cabecera"] + tabla["poblacion_centros_rural"]
    tabla["diferencia_componentes"] = tabla["poblacion_total"] - tabla["suma_componentes"]
    tabla["poblacion_consistente"] = pd.Series(pd.NA, index=tabla.index, dtype="boolean")
    tabla.loc[completas, "poblacion_consistente"] = tabla.loc[completas, "diferencia_componentes"].eq(0)
    inconsistente = tabla["poblacion_consistente"].eq(False).fillna(False)
    tabla["departamento_inconsistente"] = (
        tabla["codigo_municipio"].str[:proceso["department_code_length"]]
        .ne(tabla["codigo_departamento"]).fillna(True)
    )
    tabla["metadatos_incompletos"] = tabla[columnas_metadata].isna().any(axis=1)
    tabla["revision_territorial_pendiente"] = tabla["codigo_municipio"].isin(codigos_revision)
    tabla["estado_poblacion"] = pd.Series("disponible", index=tabla.index, dtype="string")
    tabla.loc[tabla["revision_territorial_pendiente"] | tabla["departamento_inconsistente"]
              | tabla["metadatos_incompletos"],
              "estado_poblacion"] = "pendiente_revision"
    # Un problema numerico o de suma impide usar el conjunto poblacional;
    # la marca historica permanece aparte aunque el estado sea no_utilizable.
    tabla.loc[~completas | inconsistente, "estado_poblacion"] = "no_utilizable"
    tabla["denominador_positivo"] = tabla["poblacion_total"].gt(0).fillna(False)
    tabla["poblacion_para_ratios_utilizable"] = (
        tabla["denominador_positivo"] & tabla["estado_poblacion"].eq("disponible")
    )
    # El formato de un codigo no demuestra su identidad territorial. DIVIPOLA
    # y las reglas historicas se comprobaran en las siguientes etapas.
    tabla["estado_homologacion"] = pd.Series("pendiente_revision", index=tabla.index, dtype="string")

    # Convertir NA a None solo en los ejemplos del reporte permite JSON estricto;
    # en la tabla mantenemos Int64 anulable y los valores originales de la fuente.
    casos = tabla.loc[tabla["revision_territorial_pendiente"],
                      llaves + ["municipio"] + poblaciones + ["estado_poblacion"]]
    casos = casos.astype(object).where(casos.notna(), None).to_dict("records")
    reporte.update({
        "filas_seleccionadas": len(datos), "filas_salida": len(tabla), "claves_duplicadas": 0,
        "filas_por_anio": {str(anio): int(cantidad) for anio, cantidad in tabla.groupby("anio").size().items()},
        "areas_incompletas": int(tabla["areas_incompletas"].sum()),
        "filas_con_componentes_no_utilizables": int((~completas).sum()),
        "componentes_inconsistentes": int(inconsistente.sum()),
        "departamentos_inconsistentes": int(tabla["departamento_inconsistente"].sum()),
        "metadatos_incompletos": int(tabla["metadatos_incompletos"].sum()),
        "conversiones_poblacion": {
            "faltantes": int(datos["poblacion_original"].astype("string").str.strip().replace("", pd.NA).isna().sum()),
            "no_numericas": int(errores_conversion.sum()), "no_finitas": int(no_finito.sum()),
            "negativas": int(negativos.sum()), "fraccionarias": int(fraccionarios.sum()),
        },
        "poblaciones_en_cero": {nombre: int(tabla[nombre].eq(0).sum()) for nombre in poblaciones},
        "poblacion_total_cero": int(tabla["poblacion_total"].eq(0).sum()),
        "denominadores_positivos": int(tabla["denominador_positivo"].sum()),
        "poblaciones_para_ratios_utilizables": int(tabla["poblacion_para_ratios_utilizable"].sum()),
        "codigos_revision_territorial": list(codigos_revision), "casos_revision_territorial": casos,
        "estados_poblacion": {str(estado): int(cantidad) for estado, cantidad in tabla["estado_poblacion"].value_counts().items()},
        "faltantes_por_columna_poblacional": {nombre: int(tabla[nombre].isna().sum()) for nombre in poblaciones},
    })
    # Presentamos primero la llave, nombres y poblaciones para facilitar lectura.
    primeras = llaves + columnas_metadata + poblaciones
    tabla = tabla[primeras + [nombre for nombre in tabla.columns if nombre not in primeras]]
    LOGGER.info("Poblacion preparada: %s territorios-anio de %s a %s", len(tabla), inicio, fin)
    return tabla, reporte
