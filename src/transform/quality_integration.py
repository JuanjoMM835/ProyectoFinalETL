"""Evaluar el panel integrado sin confundir coincidencia con identidad temporal."""

import copy
import math
from typing import Any, Dict, Mapping

import pandas as pd


# La primera version del contrato utiliza exactamente estas seis variables.
# Su orden en el reporte sigue el YAML, pero no se admite cambiar el conjunto.
VARIABLES_CRITICAS = {
    "poblacion_total", "poblacion_centros_rural", "accesos_t4",
    "cobertura_neta", "desercion", "reprobacion",
}
ESTADOS_RESUELTOS = {"resuelto_catalogo", "resuelto_regla_historica"}
ESTADOS_HOMOLOGACION = ESTADOS_RESUELTOS | {"pendiente_revision"}
BANDERAS_COINCIDENCIA = (
    "coincidencia_catalogo_actual", "coincidencia_poblacion",
    "coincidencia_internet", "revision_territorial_pendiente",
)


def _porcentaje(numerador: int, denominador: int) -> float:
    """Calcular el porcentaje sin redondear los controles de aceptacion."""
    # El panel vacio se rechaza antes: no se inventa un porcentaje de cumplimiento.
    return numerador / denominador * 100


def _umbral(valor: Any, opcion: str) -> float:
    """Exigir porcentajes finitos de 0 a 100, sin interpretar texto o booleanos."""
    if (not isinstance(valor, (int, float)) or isinstance(valor, bool)
            or not math.isfinite(valor) or not 0 <= valor <= 100):
        raise ValueError("{} debe ser un porcentaje entre 0 y 100.".format(opcion))
    return float(valor)


def _validar_panel(panel: pd.DataFrame, configuracion: Mapping) -> list:
    """Comprobar que las medidas describen el panel territorial anual acordado."""
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("El panel integrado debe ser un DataFrame de pandas.")
    if panel.empty:
        raise ValueError("No se evalua la calidad de un panel integrado vacio.")
    calidad = configuracion["quality"]
    criticas = calidad["critical_columns"]
    if (not isinstance(criticas, list) or len(criticas) != len(VARIABLES_CRITICAS)
            or set(criticas) != VARIABLES_CRITICAS):
        raise ValueError("La primera version evalua exactamente las seis variables criticas del contrato.")
    if calidad["completeness_denominator"] != "full_education_territorial_universe":
        raise ValueError("La completitud del panel requiere todo el universo territorial educativo.")
    if panel.columns.duplicated().any() or not all(isinstance(col, str) for col in panel.columns):
        raise ValueError("El panel tiene encabezados repetidos o no textuales.")
    llave = ["codigo_municipio", "anio"]
    banderas = list(BANDERAS_COINCIDENCIA) + [col + "_utilizable_fuente" for col in criticas]
    necesarias = llave + criticas + ["estado_homologacion"] + banderas
    faltantes = sorted(set(necesarias) - set(panel.columns))
    if faltantes:
        raise ValueError("Faltan columnas para evaluar el panel: {}".format(faltantes))
    if panel[llave].isna().any().any() or panel.duplicated(llave, keep=False).any():
        raise ValueError("La llave del panel esta incompleta o duplicada.")
    proceso = configuracion["processing"]
    if proceso["primary_key"] != llave:
        raise ValueError("La llave del panel debe ser codigo_municipio + anio.")
    longitud = proceso["municipality_code_length"]
    codigos = panel["codigo_municipio"]
    if (not isinstance(codigos.dtype, pd.StringDtype)
            or not codigos.str.fullmatch(r"[0-9]{%s}" % longitud, na=False).all()
            or codigos.eq("0" * longitud).any()):
        raise ValueError("El panel debe conservar codigos territoriales validos como texto.")
    if (not pd.api.types.is_integer_dtype(panel["anio"].dtype)
            or not panel["anio"].between(proceso["year_start"], proceso["year_end"]).all()):
        raise ValueError("El panel tiene anios invalidos o fuera del periodo.")
    estados = panel["estado_homologacion"]
    if (not isinstance(estados.dtype, pd.StringDtype)
            or estados.isna().any() or not estados.isin(ESTADOS_HOMOLOGACION).all()):
        raise ValueError("El panel tiene estados de homologacion incompletos o no reconocidos.")
    # Un texto 'True' no puede contar como una acreditacion o un dato utilizable.
    for columna in banderas:
        if not pd.api.types.is_bool_dtype(panel[columna].dtype) or panel[columna].isna().any():
            raise ValueError("{} debe ser una bandera booleana completa.".format(columna))
    for columna in criticas:
        es_tipo = (pd.api.types.is_float_dtype if columna in {
            "cobertura_neta", "desercion", "reprobacion"
        } else pd.api.types.is_integer_dtype)
        if not es_tipo(panel[columna].dtype):
            raise ValueError("{} tiene un tipo numerico distinto al contrato.".format(columna))
    return list(criticas)


def evaluar_panel(
    panel: pd.DataFrame, diagnosticos: dict, configuracion: Mapping,
    evidencia_catalogo: dict,
) -> Dict[str, Any]:
    """Medir presencia, uso local e identidad acreditada sobre todas las filas MEN.

    No modifica la tabla ni homologa territorios. El integrador debe proporcionar
    estados respaldados por evidencia; esta funcion cuenta dichos estados y
    conserva la evidencia en el reporte. Una coincidencia con DIVIPOLA no se usa
    como sustituto del estado de homologacion.
    """
    if not isinstance(diagnosticos, dict) or not isinstance(evidencia_catalogo, dict):
        raise TypeError("Los diagnosticos y la evidencia del catalogo deben ser diccionarios.")
    criticas = _validar_panel(panel, configuracion)
    calidad = configuracion["quality"]
    meta_homologacion = _umbral(calidad["min_homologation_pct"], "min_homologation_pct")
    meta_variable = _umbral(calidad["min_critical_completeness_pct"], "min_critical_completeness_pct")
    meta_conjunto = _umbral(calidad["min_joint_completeness_pct"], "min_joint_completeness_pct")
    denominador = len(panel)
    estados = panel["estado_homologacion"]
    resueltos = estados.isin(ESTADOS_RESUELTOS)
    cantidad_resueltos = int(resueltos.sum())
    porcentaje_resueltos = _porcentaje(cantidad_resueltos, denominador)

    presencias, usos_fuente, usos_panel = {}, {}, {}
    variables = {}
    for columna in criticas:
        valores = panel[columna]
        presente = (valores.notna() & ~valores.isin([float("inf"), float("-inf")])).fillna(False)
        # Un cero observado valido cuenta. La positividad necesaria para dividir
        # pertenece a los indicadores posteriores, no a esta medida de completitud.
        local = (panel[columna + "_utilizable_fuente"] & presente & valores.ge(0)).fillna(False)
        utilizable = local & resueltos
        # Recalculamos estas mascaras: no confiamos en una columna de aptitud
        # previamente escrita ni alteramos los valores originales del panel.
        presencias[columna] = presente
        usos_fuente[columna] = local
        usos_panel[columna] = utilizable
        cantidad_presente = int(presente.sum())
        cantidad_local = int(local.sum())
        cantidad_panel = int(utilizable.sum())
        porcentaje_panel = _porcentaje(cantidad_panel, denominador)
        variables[columna] = {
            "denominador": denominador,
            "numerador_presencia_numerica": cantidad_presente,
            "porcentaje_presencia_numerica": _porcentaje(cantidad_presente, denominador),
            "numerador_utilizables_fuente": cantidad_local,
            "porcentaje_utilizables_fuente": _porcentaje(cantidad_local, denominador),
            "numerador_utilizables_panel": cantidad_panel,
            "porcentaje_utilizables_panel": porcentaje_panel,
            "cumple_meta": bool(porcentaje_panel >= meta_variable),
            "meta_pct": meta_variable,
        }

    # El conjunto exige las seis variables de LA MISMA fila. No promediamos
    # porcentajes ni descartamos las filas sin coincidencia en otra fuente.
    cantidad_conjunto_presente = int(pd.DataFrame(presencias).all(axis=1).sum())
    cantidad_conjunto_local = int(pd.DataFrame(usos_fuente).all(axis=1).sum())
    cantidad_conjunto_panel = int(pd.DataFrame(usos_panel).all(axis=1).sum())
    porcentaje_conjunto_panel = _porcentaje(cantidad_conjunto_panel, denominador)
    cumple_homologacion = bool(porcentaje_resueltos >= meta_homologacion)
    cumple_conjunto = bool(porcentaje_conjunto_panel >= meta_conjunto)
    motivos = []
    if not cumple_homologacion:
        motivos.append("homologacion_panel_inferior_meta")
    for columna in criticas:
        if not variables[columna]["cumple_meta"]:
            motivos.append("completitud_{}_inferior_meta".format(columna))
    if not cumple_conjunto:
        motivos.append("completitud_conjunta_inferior_meta")
    cumple_panel = not motivos
    cantidad_internet = int(panel["coincidencia_internet"].sum())
    advertencias = [
        "Los porcentajes de presencia y utilizacion local usan todas las filas del universo MEN, no las filas de cada Silver.",
        "La coincidencia con el catalogo actual no acredita por si sola la vigencia territorial para cada anio.",
        "La utilizacion en el panel exige controles de fuente e identidad territorial acreditada; los valores observados se conservan.",
        "Un cero valido cuenta como dato completo, pero puede impedir un indicador con ese valor como denominador.",
    ]
    if cantidad_resueltos == 0:
        advertencias.append(
            "El 0 % de utilizacion validada del panel expresa falta de identidad temporal acreditada para Gold, no ausencia de los datos numericos."
        )

    return {
        "version_reporte": "1.0", "etapa": "integracion", "estado": "exploratorio",
        "filas_panel": denominador, "denominador_panel": denominador,
        "diagnosticos": copy.deepcopy(diagnosticos),
        "homologacion": {
            "numerador_resueltos": cantidad_resueltos, "denominador": denominador,
            "porcentaje": porcentaje_resueltos, "meta_pct": meta_homologacion,
            "cumple_meta": cumple_homologacion,
            "estados": {str(estado): int(cantidad) for estado, cantidad in estados.value_counts().items()},
            "codigos_distintos_resueltos": int(panel.loc[resueltos, "codigo_municipio"].nunique()),
            "codigos_distintos_pendientes": int(panel.loc[~resueltos, "codigo_municipio"].nunique()),
            "evidencia_catalogo": copy.deepcopy(evidencia_catalogo),
        },
        "variables_criticas": variables,
        "conjunto_critico": {
            "denominador": denominador,
            "numerador_presencia_numerica": cantidad_conjunto_presente,
            "porcentaje_presencia_numerica": _porcentaje(cantidad_conjunto_presente, denominador),
            "numerador_utilizables_fuente": cantidad_conjunto_local,
            "porcentaje_utilizables_fuente": _porcentaje(cantidad_conjunto_local, denominador),
            "numerador_utilizables_panel": cantidad_conjunto_panel,
            "porcentaje_utilizables_panel": porcentaje_conjunto_panel,
            "cumple_meta": cumple_conjunto,
        },
        "coincidencia_internet_t4": {
            "numerador": cantidad_internet, "denominador": denominador,
            "porcentaje": _porcentaje(cantidad_internet, denominador),
        },
        "aceptacion_panel": {
            "estado": "cumple" if cumple_panel else "no_cumple",
            "cumple_meta": bool(cumple_panel), "motivos": motivos,
        },
        "advertencias": advertencias,
    }
