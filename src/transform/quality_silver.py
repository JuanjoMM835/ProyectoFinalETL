"""Comprobar las cuatro tablas Silver sin integrar ni aprobar el panel Gold."""

import copy
from typing import Any, Dict, Mapping

import pandas as pd


# Los estados de la fuente determinan uso local; no resuelven homologacion.
CRITICAS = {
    "educacion": ["cobertura_neta", "desercion", "reprobacion"],
    "poblacion": ["poblacion_total", "poblacion_centros_rural"],
    "internet": ["accesos_t4"],
    "divipola": [],
}
ESTADOS = {
    "educacion": ["estado_cobertura_neta", "estado_desercion", "estado_reprobacion"],
    "poblacion": ["estado_poblacion"],
    "internet": ["estado_internet"],
    "divipola": ["estado_catalogo"],
}


def _porcentaje(numerador: int, denominador: int) -> Any:
    """Un conjunto vacio tiene porcentaje desconocido, no NaN ni 100 %."""
    return numerador / denominador * 100 if denominador else None


def _validar_tabla(nombre: str, tabla: pd.DataFrame, configuracion: Mapping) -> list:
    """Detener la persistencia por errores de estructura o de llave."""
    llave = ["codigo_municipio"] if nombre == "divipola" else ["codigo_municipio", "anio"]
    obligatorias = llave + CRITICAS[nombre] + ESTADOS[nombre]
    if nombre == "poblacion":
        obligatorias += ["poblacion_consistente", "poblacion_para_ratios_utilizable"]
    if nombre == "internet":
        obligatorias += ["accesos_para_indicadores_utilizables"]
    if tabla.columns.duplicated().any() or not all(isinstance(col, str) for col in tabla.columns):
        raise ValueError("{} tiene encabezados repetidos o no textuales.".format(nombre))
    ausentes = sorted(set(obligatorias) - set(tabla.columns))
    if ausentes:
        raise ValueError("Faltan columnas Silver en {}: {}".format(nombre, ausentes))
    if tabla[llave].isna().any().any() or tabla.duplicated(llave, keep=False).any():
        raise ValueError("{} tiene llaves incompletas o duplicadas.".format(nombre))
    codigos = tabla["codigo_municipio"]
    longitud = configuracion["processing"]["municipality_code_length"]
    if (not isinstance(codigos.dtype, pd.StringDtype)
            or not codigos.str.fullmatch(r"[0-9]{%s}" % longitud, na=False).all()
            or codigos.eq("0" * longitud).any()):
        raise ValueError("{} no conserva codigos territoriales validos como texto.".format(nombre))
    if nombre != "divipola":
        inicio, fin = configuracion["processing"]["year_start"], configuracion["processing"]["year_end"]
        if (not pd.api.types.is_integer_dtype(tabla["anio"].dtype)
                or not tabla["anio"].between(inicio, fin).all()):
            raise ValueError("{} tiene anios invalidos o fuera del periodo.".format(nombre))
    # La utilizabilidad se consulta como estado; un estado faltante no se oculta.
    if tabla[ESTADOS[nombre]].isna().any().any():
        raise ValueError("{} tiene estados de calidad faltantes.".format(nombre))
    for columna in ESTADOS[nombre] + (["estado_homologacion"] if "estado_homologacion" in tabla else []):
        if not isinstance(tabla[columna].dtype, pd.StringDtype):
            raise ValueError("{} debe conservar {} como texto tipado.".format(nombre, columna))
    # Guardar texto que parece numero no equivale a guardar el esquema acordado.
    numericas = CRITICAS[nombre] + (["poblacion_cabecera"] if nombre == "poblacion" else [])
    for columna in numericas:
        if columna not in tabla:
            raise ValueError("Falta la columna Silver {}.".format(columna))
        es_tipo = pd.api.types.is_float_dtype if nombre == "educacion" else pd.api.types.is_integer_dtype
        if not es_tipo(tabla[columna].dtype):
            raise ValueError("{} tiene un tipo numerico incorrecto en {}.".format(nombre, columna))
    banderas = {"poblacion": ["poblacion_consistente", "poblacion_para_ratios_utilizable"],
                "internet": ["accesos_para_indicadores_utilizables"]}.get(nombre, [])
    for columna in banderas:
        if not pd.api.types.is_bool_dtype(tabla[columna].dtype):
            raise ValueError("{} requiere una bandera booleana en {}.".format(nombre, columna))
    return llave


def construir_reporte_silver(
    tablas: Mapping[str, pd.DataFrame], reportes: Mapping[str, Dict[str, Any]],
    configuracion: Mapping[str, Any], ejecucion_id: str,
) -> Dict[str, Any]:
    """Devolver calidad local con sus denominadores y preservar los reportes E/T."""
    if set(tablas) != set(CRITICAS) or set(reportes) != set(CRITICAS):
        raise ValueError("Silver requiere tablas y reportes de las cuatro fuentes.")
    fuentes = {}
    for nombre in CRITICAS:
        tabla = tablas[nombre]
        llave = _validar_tabla(nombre, tabla, configuracion)
        total = len(tabla)
        if reportes[nombre]["filas_salida"] != total:
            raise ValueError("El reporte de {} no corresponde a la tabla recibida.".format(nombre))
        criticas = {}
        for columna in CRITICAS[nombre]:
            valores = pd.to_numeric(tabla[columna], errors="coerce")
            presentes = valores.notna() & ~valores.isin([float("inf"), float("-inf")])
            # Presencia numerica y utilizabilidad semantica son medidas distintas.
            if nombre == "educacion":
                utilizables = tabla["estado_" + columna].eq("disponible")
            elif nombre == "poblacion":
                utilizables = tabla["estado_poblacion"].eq("disponible") & tabla["poblacion_consistente"].fillna(False)
            else:
                utilizables = tabla["estado_internet"].eq("disponible") & tabla["accesos_para_indicadores_utilizables"].fillna(False)
            utilizables = (utilizables & presentes & valores.ge(0)).fillna(False)
            criticas[columna] = {
                "denominador": total,
                "numerador_presencia_numerica": int(presentes.sum()),
                "porcentaje_presencia_numerica": _porcentaje(int(presentes.sum()), total),
                "numerador_utilizables_fuente": int(utilizables.sum()),
                "porcentaje_utilizables_fuente": _porcentaje(int(utilizables.sum()), total),
            }
        # Contar banderas conserva excepciones y separa calculabilidad de dato.
        controles = {
            columna: int(tabla[columna].fillna(False).sum())
            for columna in tabla.columns if pd.api.types.is_bool_dtype(tabla[columna].dtype)
        }
        fuentes[nombre] = {
            "filas": total, "llave": llave,
            "granularidad": "catalogo_territorial" if nombre == "divipola" else "territorio_anio",
            "llaves_incompletas": 0, "llaves_duplicadas": 0,
            "codigos_distintos": int(tabla["codigo_municipio"].nunique()),
            "filas_por_anio": {} if nombre == "divipola" else {
                str(anio): int(cantidad) for anio, cantidad in tabla.groupby("anio").size().items()
            },
            "tipos_columnas": {columna: str(tipo) for columna, tipo in tabla.dtypes.items()},
            "faltantes_por_columna": {columna: int(cantidad) for columna, cantidad in tabla.isna().sum().items()},
            "estados": {columna: {str(estado): int(cantidad) for estado, cantidad in tabla[columna].value_counts().items()}
                        for columna in ESTADOS[nombre] + (["estado_homologacion"] if "estado_homologacion" in tabla else [])},
            "criticas_en_fuente": criticas, "controles_adicionales": controles,
            "reporte_transformacion": copy.deepcopy(reportes[nombre]),
        }
    calidad = configuracion["quality"]
    return {
        "version_reporte": "1.0", "version_contrato": configuracion["project"]["data_contract"]["version"],
        "ejecucion_id": ejecucion_id, "etapa": "silver", "estado": "exploratorio",
        "controles_estructura": "superados",
        "periodo": {"inicio": configuracion["processing"]["year_start"], "fin": configuracion["processing"]["year_end"]},
        "fuentes": fuentes,
        "aceptacion_panel": {
            "estado": "no_evaluada",
            "motivo": "La integracion y homologacion temporal del panel se implementaran en el punto 5.",
            "denominador_requerido": calidad["completeness_denominator"],
            "filas_universo_educativo": len(tablas["educacion"]),
            "variables_criticas": list(calidad["critical_columns"]),
            "umbrales_pct": {
                "homologacion": calidad["min_homologation_pct"],
                "completitud_variable": calidad["min_critical_completeness_pct"],
                "completitud_conjunta": calidad["min_joint_completeness_pct"],
            },
            # None produce null en JSON: no afirmamos que el panel haya pasado.
            "homologacion_panel": None, "completitud_seis_variables": None,
            "completitud_conjunta": None, "coincidencia_internet_t4": None,
        },
    }
