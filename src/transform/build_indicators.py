"""Calcular indicadores anuales con condiciones, procedencia y motivos de ausencia."""

import math
from typing import Any, Dict, Mapping, Tuple

import pandas as pd


INDICADORES = (
    "accesos_por_100_habitantes", "porcentaje_centros_rural",
    "crecimiento_anual_accesos", "porcentaje_cobertura_neta", "tasa_desercion",
    "tasa_reprobacion",
)
INDICE_PRIORIDAD = "indice_prioridad"
COMPONENTES_PRIORIDAD = (
    "accesos_por_100_habitantes", "tasa_desercion", "porcentaje_cobertura_neta",
)
RESUELTOS = {"resuelto_catalogo", "resuelto_regla_historica"}
FORMULAS = {
    "accesos_por_100_habitantes": "accesos_t4 / poblacion_total * 100",
    "porcentaje_centros_rural": "poblacion_centros_rural / poblacion_total * 100",
    "crecimiento_anual_accesos": "(accesos_t4 - accesos_t4_anterior) / accesos_t4_anterior * 100",
    "porcentaje_cobertura_neta": "valor suministrado por MEN: cobertura_neta (porcentaje)",
    "tasa_desercion": "valor suministrado por MEN: desercion (porcentaje)",
    "tasa_reprobacion": "valor suministrado por MEN: reprobacion (porcentaje)",
}


def _validar(panel: pd.DataFrame, configuracion: Mapping) -> None:
    """Detener el calculo por estructura incorrecta, sin alterar el universo."""
    if not isinstance(panel, pd.DataFrame) or panel.empty:
        raise ValueError("Los indicadores requieren un panel territorial anual no vacio.")
    if panel.columns.duplicated().any():
        raise ValueError("El panel no puede tener encabezados duplicados.")
    enteros = ["anio", "poblacion_total", "poblacion_cabecera",
               "poblacion_centros_rural", "accesos_t4", "trimestre_referencia"]
    textos = ["codigo_municipio", "estado_poblacion", "estado_internet", "estado_homologacion"]
    banderas = ["poblacion_consistente", "poblacion_total_utilizable_fuente",
                "poblacion_centros_rural_utilizable_fuente", "accesos_t4_utilizable_fuente"]
    faltantes = sorted(set(enteros + textos + banderas) - set(panel.columns))
    if faltantes:
        raise ValueError("Faltan columnas del panel para indicadores: {}".format(faltantes))
    for columna in enteros:
        if not pd.api.types.is_integer_dtype(panel[columna].dtype):
            raise ValueError("{} debe conservar su tipo entero.".format(columna))
    for columna in textos:
        if not isinstance(panel[columna].dtype, pd.StringDtype):
            raise ValueError("{} debe conservar texto tipado.".format(columna))
    for columna in banderas + [nombre for nombre in (
            "departamento_inconsistente_entre_fuentes",
            "departamento_desconocido_en_coincidencias") if nombre in panel]:
        if not pd.api.types.is_bool_dtype(panel[columna].dtype):
            raise ValueError("{} debe ser una bandera booleana.".format(columna))
    llave = ["codigo_municipio", "anio"]
    proceso = configuracion["processing"]
    if (proceso["primary_key"] != llave or proceso["internet_quarter"] != 4
            or proceso["allow_quarter_fallback"] or proceso["impute_missing_as_zero"]
            or proceso["include_previous_year_for_growth"]):
        raise ValueError("Los indicadores requieren el contrato anual, T4 y ausencia de imputacion.")
    if panel[llave].isna().any().any() or panel.duplicated(llave).any():
        raise ValueError("La llave territorial anual esta incompleta o repetida.")
    if (not panel["codigo_municipio"].str.fullmatch(r"[0-9]{5}", na=False).all()
            or panel["codigo_municipio"].eq("00000").any()):
        raise ValueError("Los codigos territoriales deben ser texto de cinco digitos.")
    if not panel["anio"].between(proceso["year_start"], proceso["year_end"]).all():
        raise ValueError("Hay anios fuera del periodo del contrato.")
    if (panel[textos[1:]].isna().any().any()
            or not panel["estado_homologacion"].isin(RESUELTOS | {"pendiente_revision"}).all()):
        raise ValueError("Los estados del panel estan incompletos o no son reconocidos.")
    reservadas = {campo for nombre in INDICADORES for campo in (
        nombre, "estado_" + nombre, "motivo_" + nombre,
        nombre + "_diagnostico", "estado_" + nombre + "_diagnostico",
        "motivo_" + nombre + "_diagnostico",
    )}
    reservadas.update({
        INDICE_PRIORIDAD, "estado_" + INDICE_PRIORIDAD, "motivo_" + INDICE_PRIORIDAD,
        "categoria_prioridad", INDICE_PRIORIDAD + "_diagnostico",
        "estado_" + INDICE_PRIORIDAD + "_diagnostico",
        "motivo_" + INDICE_PRIORIDAD + "_diagnostico",
        "categoria_prioridad_diagnostico",
    })
    if reservadas.intersection(panel.columns):
        raise ValueError("El panel ya contiene columnas reservadas para indicadores.")


def _bandera(fila: Mapping, nombre: str) -> bool:
    """Una marca desconocida nunca acredita utilizacion."""
    valor = fila.get(nombre, False)
    return not pd.isna(valor) and bool(valor)


def _metadatos(fila: Mapping) -> Tuple[str, str]:
    """Separar contradiccion departamental de identidad temporal pendiente."""
    if _bandera(fila, "departamento_inconsistente_entre_fuentes"):
        return "pendiente_revision", "departamentos_incompatibles"
    if _bandera(fila, "departamento_desconocido_en_coincidencias"):
        return "pendiente_revision", "departamentos_no_documentados"
    return "disponible", "calculable_controles_fuente"


def _poblacion(fila: Mapping, rural: bool = False) -> Tuple[str, str]:
    """Revalidar componentes exactos, calidad local y denominador positivo."""
    estado = fila["estado_poblacion"]
    if estado == "sin_coincidencia":
        return "no_calculable", "sin_coincidencia_poblacion"
    if estado == "pendiente_revision":
        return "pendiente_revision", "revision_poblacion"
    cantidades = [fila[columna] for columna in (
        "poblacion_total", "poblacion_cabecera", "poblacion_centros_rural")]
    if any(pd.isna(valor) for valor in cantidades):
        return "no_calculable", "poblacion_incompleta"
    # Convertir a int Python evita desbordar al sumar componentes Int64 grandes.
    total, cabecera, centros = map(int, cantidades)
    if min(total, cabecera, centros) < 0:
        return "no_calculable", "poblacion_negativa"
    if total != cabecera + centros or not _bandera(fila, "poblacion_consistente"):
        return "no_calculable", "componentes_poblacionales_inconsistentes"
    if total == 0:
        return "no_calculable", "poblacion_total_no_positiva"
    if estado != "disponible" or not _bandera(fila, "poblacion_total_utilizable_fuente"):
        return "no_calculable", "poblacion_no_utilizable"
    if rural and not _bandera(fila, "poblacion_centros_rural_utilizable_fuente"):
        return "no_calculable", "poblacion_rural_no_utilizable"
    return _metadatos(fila)


def _internet(fila: Mapping) -> Tuple[str, str]:
    """Usar solo accesos completos y utilizables de T4; nunca un subtotal."""
    if fila["estado_internet"] == "sin_reporte_t4":
        return "no_calculable", "sin_reporte_t4"
    if fila["estado_internet"] == "pendiente_revision":
        return "pendiente_revision", "revision_internet"
    if pd.isna(fila["accesos_t4"]):
        return "no_calculable", "accesos_faltantes"
    if int(fila["accesos_t4"]) < 0:
        return "no_calculable", "accesos_negativos"
    if pd.isna(fila["trimestre_referencia"]) or int(fila["trimestre_referencia"]) != 4:
        return "no_calculable", "referencia_no_t4"
    if fila["estado_internet"] != "disponible" or not _bandera(fila, "accesos_t4_utilizable_fuente"):
        return "no_calculable", "accesos_no_utilizables"
    return _metadatos(fila)


def _finito(valor: float, estado: str, motivo: str) -> Tuple[Any, str, str]:
    """No guardar infinitos como si un indicador fuera calculable."""
    if not math.isfinite(valor):
        return pd.NA, "no_calculable", "resultado_no_finito"
    return valor, estado, motivo


def _ratio(fila: Mapping, rural: bool) -> Tuple[Any, str, str]:
    """Calcular una razon con controles de las variables que realmente utiliza."""
    estado, motivo = _poblacion(fila, rural)
    if estado != "disponible":
        return pd.NA, estado, motivo
    if not rural:
        estado, motivo = _internet(fila)
        if estado != "disponible":
            return pd.NA, estado, motivo
    numerador = int(fila["poblacion_centros_rural" if rural else "accesos_t4"])
    valor = numerador / int(fila["poblacion_total"]) * 100
    # Cero observado produce cero; no se recorta una razon de accesos superior a 100.
    return _finito(valor, "disponible", "calculable_controles_fuente")


def _crecimiento(fila: Mapping, anterior: Any, inicio: int) -> Tuple[Any, str, str]:
    """Exigir el anio previo consecutivo del mismo codigo, sin saltar ausencias."""
    if int(fila["anio"]) == inicio:
        return pd.NA, "no_aplica", "sin_anio_previo_en_alcance"
    if anterior is None:
        return pd.NA, "no_calculable", "sin_anio_anterior_consecutivo"
    for datos, sufijo in ((fila, ""), (anterior, "_anterior")):
        estado, motivo = _internet(datos)
        if estado != "disponible":
            return pd.NA, estado, motivo + sufijo
    anteriores = int(anterior["accesos_t4"])
    if anteriores == 0:
        return pd.NA, "no_calculable", "accesos_anteriores_no_positivos"
    # Restar enteros antes de convertir a decimal conserva diferencias de una unidad.
    valor = (int(fila["accesos_t4"]) - anteriores) / anteriores * 100
    return _finito(valor, "disponible", "calculable_controles_fuente")


def _educativo(fila: Mapping, columna: str) -> Tuple[Any, str, str]:
    """Exponer un indicador MEN sin sustituir ni recortar su observación."""
    valor = fila.get(columna, pd.NA)
    if pd.isna(valor):
        return pd.NA, "no_calculable", "valor_educativo_faltante"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return pd.NA, "no_calculable", "valor_educativo_no_numerico"
    if not math.isfinite(numero) or numero < 0:
        return pd.NA, "no_calculable", "valor_educativo_no_utilizable"
    estado = fila.get("estado_" + columna, "faltante")
    if estado == "pendiente_revision":
        return pd.NA, "pendiente_revision", "revision_" + columna
    if estado != "disponible":
        return pd.NA, "no_calculable", "estado_" + columna + "_no_disponible"
    if not _bandera(fila, columna + "_utilizable_fuente"):
        return pd.NA, "no_calculable", columna + "_no_utilizable"
    return _finito(numero, "disponible", "calculable_controles_fuente")


def _componente_prioridad(valor: Any, invertido: bool) -> float:
    """Normalizar a [0, 1] para el índice; no modifica el valor Gold original."""
    numero = min(max(float(valor), 0.0), 100.0) / 100.0
    return 1.0 - numero if invertido else numero


def _prioridad(fila: Mapping, configuracion: Mapping[str, Any], sufijo: str = "") -> Tuple[Any, str, str, str]:
    """Calcular prioridad alta/media/baja con tres componentes explícitos."""
    nombres = [nombre + sufijo for nombre in COMPONENTES_PRIORIDAD]
    estados = [fila.get("estado_" + nombre, "no_disponible") for nombre in nombres]
    if any(estado == "pendiente_revision" for estado in estados):
        return pd.NA, "pendiente_revision", "componente_pendiente_revision", pd.NA
    if any(estado != "disponible" for estado in estados):
        return pd.NA, "no_calculable", "componente_no_disponible", pd.NA
    valores = [fila.get(nombre, pd.NA) for nombre in nombres]
    if any(pd.isna(valor) for valor in valores):
        return pd.NA, "no_calculable", "componente_faltante", pd.NA
    try:
        score = (
            float(configuracion["indicators"]["priority_index"]["weights"]["connectivity_deficit"])
            * _componente_prioridad(valores[0], invertido=True)
            + float(configuracion["indicators"]["priority_index"]["weights"]["dropout"])
            * _componente_prioridad(valores[1], invertido=False)
            + float(configuracion["indicators"]["priority_index"]["weights"]["coverage_deficit"])
            * _componente_prioridad(valores[2], invertido=True)
        )
    except (TypeError, ValueError, KeyError):
        return pd.NA, "no_calculable", "configuracion_indice_invalida", pd.NA
    if not math.isfinite(score):
        return pd.NA, "no_calculable", "resultado_no_finito", pd.NA
    umbral_medio = float(configuracion["indicators"]["priority_index"]["thresholds"]["medium"])
    umbral_alto = float(configuracion["indicators"]["priority_index"]["thresholds"]["high"])
    categoria = "baja" if score < umbral_medio else "media" if score < umbral_alto else "alta"
    return score, "disponible", "calculable_componentes_prioridad", categoria


def construir_indicadores(
    panel: pd.DataFrame, configuracion: Mapping[str, Any],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Añadir seis indicadores, diagnósticos e índice de prioridad.

    Las columnas canonicas exigen identidad acreditada. Los candidatos locales
    terminan en _diagnostico y no acreditan Gold; sirven para conciliar formulas
    mientras se resuelven las incidencias de identidad. No cambian valores fuente.
    """
    _validar(panel, configuracion)
    datos = panel.copy(deep=True)
    # Un indice tecnico repetido no define identidad: las llaves estan en columnas.
    filas = panel.to_dict(orient="records")
    por_llave = {(fila["codigo_municipio"], int(fila["anio"])): fila for fila in filas}
    salidas = {nombre: [] for nombre in INDICADORES}
    diagnosticos = {nombre: [] for nombre in INDICADORES}
    inicio = configuracion["processing"]["year_start"]
    for fila in filas:
        anterior = por_llave.get((fila["codigo_municipio"], int(fila["anio"]) - 1))
        candidatos = {
            "accesos_por_100_habitantes": _ratio(fila, rural=False),
            "porcentaje_centros_rural": _ratio(fila, rural=True),
            "crecimiento_anual_accesos": _crecimiento(fila, anterior, inicio),
            "porcentaje_cobertura_neta": _educativo(fila, "cobertura_neta"),
            "tasa_desercion": _educativo(fila, "desercion"),
            "tasa_reprobacion": _educativo(fila, "reprobacion"),
        }
        for nombre, candidato in candidatos.items():
            diagnosticos[nombre].append(candidato)
            valor, estado, motivo = candidato
            if estado == "disponible":
                if fila["estado_homologacion"] not in RESUELTOS:
                    valor, estado, motivo = pd.NA, "pendiente_revision", "identidad_territorial_pendiente"
                elif nombre == "crecimiento_anual_accesos" and anterior["estado_homologacion"] not in RESUELTOS:
                    valor, estado, motivo = pd.NA, "pendiente_revision", "identidad_anterior_pendiente"
                else:
                    motivo = "calculable"
            salidas[nombre].append((valor, estado, motivo))

    reporte_indicadores = {}
    for nombre in INDICADORES:
        # pd.array asigna por posicion y conserva tambien indices tecnicos repetidos.
        for registros, sufijo in ((salidas[nombre], ""), (diagnosticos[nombre], "_diagnostico")):
            datos[nombre + sufijo] = pd.array([fila[0] for fila in registros], dtype="Float64")
            datos["estado_" + nombre + sufijo] = pd.array([fila[1] for fila in registros], dtype="string")
            datos["motivo_" + nombre + sufijo] = pd.array([fila[2] for fila in registros], dtype="string")
        cantidad = int(datos[nombre].notna().sum())
        cantidad_local = int(datos[nombre + "_diagnostico"].notna().sum())
        reporte_indicadores[nombre] = {
            "formula": FORMULAS[nombre], "denominador": len(datos),
            "numerador_calculables": cantidad, "pct_calculables": cantidad / len(datos) * 100,
            "numerador_diagnostico": cantidad_local, "pct_diagnostico": cantidad_local / len(datos) * 100,
            "estados": {str(estado): int(total) for estado, total in datos["estado_" + nombre].value_counts().items()},
            "motivos": {str(motivo): int(total) for motivo, total in datos["motivo_" + nombre].value_counts().items()},
            "motivos_diagnostico": {str(motivo): int(total) for motivo, total in datos["motivo_" + nombre + "_diagnostico"].value_counts().items()},
        }
    # El índice se calcula después de publicar las seis columnas de indicadores,
    # para que cada componente conserve exactamente su estado canónico o diagnóstico.
    filas_gold = datos.to_dict(orient="records")
    prioridad = [_prioridad(fila, configuracion) for fila in filas_gold]
    prioridad_diagnostica = [_prioridad(fila, configuracion, "_diagnostico") for fila in filas_gold]
    for registros, sufijo in ((prioridad, ""), (prioridad_diagnostica, "_diagnostico")):
        datos[INDICE_PRIORIDAD + sufijo] = pd.array([fila[0] for fila in registros], dtype="Float64")
        datos["estado_" + INDICE_PRIORIDAD + sufijo] = pd.array([fila[1] for fila in registros], dtype="string")
        datos["motivo_" + INDICE_PRIORIDAD + sufijo] = pd.array([fila[2] for fila in registros], dtype="string")
        datos["categoria_prioridad" + sufijo] = pd.array([fila[3] for fila in registros], dtype="string")
    pesos = configuracion["indicators"]["priority_index"]["weights"]
    umbrales = configuracion["indicators"]["priority_index"]["thresholds"]
    reporte_indice = {
        "formula": "0.4 * deficit_conectividad + 0.3 * desercion + 0.3 * deficit_cobertura",
        "componentes": {
            "deficit_conectividad": "1 - clip(accesos_por_100_habitantes, 0, 100) / 100",
            "desercion": "clip(tasa_desercion, 0, 100) / 100",
            "deficit_cobertura": "1 - clip(porcentaje_cobertura_neta, 0, 100) / 100",
        },
        "pesos": dict(pesos), "umbrales": dict(umbrales),
        "denominador": len(datos),
        "numerador_calculables": int(datos[INDICE_PRIORIDAD].notna().sum()),
        "numerador_diagnostico": int(datos[INDICE_PRIORIDAD + "_diagnostico"].notna().sum()),
        "categorias": {str(categoria): int(total) for categoria, total in datos["categoria_prioridad"].value_counts().items()},
        "categorias_diagnostico": {str(categoria): int(total) for categoria, total in datos["categoria_prioridad_diagnostico"].value_counts().items()},
    }
    # Solo las columnas anadidas difieren: comprobar universo, orden y originales.
    pd.testing.assert_frame_equal(datos[panel.columns], panel, check_exact=True)
    return datos, {
        "version_reporte": "1.0", "etapa": "indicadores", "estado": "exploratorio",
        "filas_panel": len(datos), "denominador_panel": len(datos),
        "indicadores": reporte_indicadores,
        "indice_prioridad": reporte_indice,
        "advertencias": [
            "Los campos _diagnostico aplican controles locales y no acreditan identidad territorial.",
            "Accesos por 100 habitantes mide conexiones respecto a poblacion, no personas conectadas.",
            "El crecimiento del primer anio no aplica; las demas ausencias no se sustituyen por cero.",
            "Los tres indicadores educativos exponen el valor MEN y conservan sus controles de utilizabilidad.",
            "El índice usa límites fijos 0–100 solo para normalizar componentes; no altera los valores fuente.",
            "La categoría alta empieza en el umbral alto, la media en el umbral medio y el resto es baja.",
        ],
    }
