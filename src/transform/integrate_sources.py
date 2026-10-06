"""Integrar Silver sobre el universo MEN, sin perder filas ni inventar identidades."""

import copy
import math
from typing import Any, Dict, Mapping, Optional, Tuple

import pandas as pd

from src.transform.quality_silver import _validar_tabla
from src.transform.quality_integration import evaluar_panel
from src.transform.resolve_territory import aplicar_evidencia_territorial


LLAVE = ["codigo_municipio", "anio"]
FUENTES = ["educacion", "poblacion", "internet", "divipola"]
# Estos campos tienen un propietario unico y se mantienen accesibles en el panel.
CANONICAS = {
    "educacion": {"cobertura_neta", "desercion", "reprobacion", "estado_cobertura_neta", "estado_desercion", "estado_reprobacion"},
    "poblacion": {"poblacion_total", "poblacion_cabecera", "poblacion_centros_rural", "estado_poblacion", "poblacion_consistente", "denominador_positivo", "poblacion_para_ratios_utilizable"},
    "internet": {"accesos_t4", "accesos_validos_parcial", "trimestre_referencia", "estado_internet", "accesos_para_indicadores_utilizables"},
    "divipola": set(),
}


def _registros_json(tabla: pd.DataFrame) -> list:
    """Convertir diagnosticos pequenos a JSON nativo, conservando los faltantes."""
    registros = []
    for fila in tabla.itertuples(index=False, name=None):
        registro = {}
        for nombre, valor in zip(tabla.columns, fila):
            if pd.isna(valor):
                valor = None
            elif hasattr(valor, "item"):
                valor = valor.item()
            if isinstance(valor, float) and not math.isfinite(valor):
                # El original permanece en Silver; JSON no admite Infinity.
                valor = str(valor)
            registro[nombre] = valor
        registros.append(registro)
    return registros


def _preparar(nombre: str, tabla: pd.DataFrame, configuracion: Mapping) -> pd.DataFrame:
    """Validar cada llave y dar un prefijo a sus campos auxiliares de procedencia."""
    _validar_tabla(nombre, tabla, configuracion)
    metadatos = ["codigo_departamento", "municipio", "departamento"]
    if nombre == "divipola":
        metadatos += ["tipo_territorio"]
    if any(columna not in tabla for columna in metadatos):
        raise ValueError("Faltan metadatos territoriales de {}.".format(nombre))
    if any(not isinstance(tabla[columna].dtype, pd.StringDtype) for columna in metadatos):
        raise ValueError("Los metadatos territoriales de {} deben ser texto tipado.".format(nombre))
    if any("__" in columna for columna in tabla.columns):
        raise ValueError("Los encabezados con doble guion bajo estan reservados para la procedencia.")
    claves = ["codigo_municipio"] if nombre == "divipola" else LLAVE
    renombrar = {columna: columna if columna in claves or columna in CANONICAS[nombre]
                 else nombre + "__" + columna for columna in tabla.columns}
    return tabla.copy(deep=True).rename(columns=renombrar).reset_index(drop=True)


def _unir(base: pd.DataFrame, otra: pd.DataFrame, nombre: str, cantidad: int) -> pd.DataFrame:
    """Usar union izquierda y exigir la cardinalidad apropiada de cada fuente."""
    claves = ["codigo_municipio"] if nombre == "divipola" else LLAVE
    cardinalidad = "many_to_one" if nombre == "divipola" else "one_to_one"
    indicador = "_union_" + nombre
    resultado = base.merge(otra, on=claves, how="left", sort=False,
                           validate=cardinalidad, indicator=indicador, suffixes=(False, False))
    if len(resultado) != cantidad or resultado.duplicated(LLAVE).any():
        raise ValueError("La union con {} altero el universo educativo.".format(nombre))
    columna = "coincidencia_catalogo_actual" if nombre == "divipola" else "coincidencia_" + nombre
    resultado[columna] = resultado[indicador].eq("both").astype("boolean")
    return resultado.drop(columns=indicador)


def _comparar_departamentos(panel: pd.DataFrame, fuente: str, coincidencia: str) -> pd.Series:
    """Una ausencia produce desconocido; una contradiccion nunca se corrige."""
    comparacion = panel["codigo_departamento"].eq(panel[fuente + "__codigo_departamento"]).astype("boolean")
    return comparacion.where(panel[coincidencia], pd.NA)


def _consistencia_poblacional(panel: pd.DataFrame) -> pd.Series:
    """Verificar total y componentes con enteros Python para evitar overflow."""
    columnas = ["poblacion_total", "poblacion_cabecera", "poblacion_centros_rural"]
    valores = []
    for total, cabecera, rural in panel[columnas].itertuples(index=False, name=None):
        valido = not any(pd.isna(valor) for valor in (total, cabecera, rural))
        valores.append(valido and min(int(total), int(cabecera), int(rural)) >= 0
                       and int(total) == int(cabecera) + int(rural))
    return pd.Series(valores, index=panel.index, dtype="boolean")


def integrar_fuentes(
    tablas: Mapping[str, pd.DataFrame], configuracion: Mapping[str, Any],
    evidencia_catalogo: Optional[Dict[str, Any]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Devolver panel y diagnostico; una coincidencia actual no acredita historia.

    El CSV actual no acredita vigencia anual. Las referencias oficiales anuales
    solo resuelven filas por codigo y anio exactos; los casos historicos siguen
    pendientes y no se habilita homologacion mediante un booleano global.
    """
    if set(tablas) != set(FUENTES):
        raise ValueError("La integracion requiere las cuatro tablas Silver.")
    proceso, calidad = configuracion["processing"], configuracion["quality"]
    if (proceso["baseline_source"] != "education_stats" or proceso["primary_key"] != LLAVE
            or not calidad["preserve_unmatched_rows"]):
        raise ValueError("El contrato exige preservar el universo educativo por codigo y anio.")
    if (proceso["internet_quarter"] != 4 or proceso["allow_quarter_fallback"]
            or proceso["impute_missing_as_zero"]):
        raise ValueError("La integracion requiere T4 exclusivo y faltantes sin imputacion.")
    evidencia = copy.deepcopy(evidencia_catalogo or {
        "vigencia_historica_verificada": False, "anio_inicio": None, "anio_fin": None,
        "referencia": None, "motivo": "Catalogo disponible sin vigencia anual documentada.",
    })
    if evidencia.get("vigencia_historica_verificada") or evidencia.get("reglas_verificadas"):
        raise ValueError("No se activa homologacion por una bandera global; se requieren reglas temporales por codigo respaldadas e implementadas.")
    preparados = {nombre: _preparar(nombre, tablas[nombre], configuracion) for nombre in FUENTES}
    panel = preparados["educacion"]
    cantidad = len(panel)
    if cantidad == 0:
        raise ValueError("El universo educativo seleccionado no puede estar vacio.")
    # El orden de las filas MEN se conserva; los extras no crean filas en el panel.
    claves_originales = panel[LLAVE].copy()
    for nombre in ("poblacion", "internet", "divipola"):
        panel = _unir(panel, preparados[nombre], nombre, cantidad)
    pd.testing.assert_frame_equal(panel[LLAVE], claves_originales, check_exact=True)

    # Los nombres de referencia siguen siendo MEN; los del catalogo se distinguen.
    for columna in ("codigo_departamento", "municipio", "departamento"):
        panel[columna] = panel["educacion__" + columna].copy()
    panel["fuente_nombre_territorial"] = pd.Series("educacion", index=panel.index, dtype="string")
    for columna in ("codigo_departamento", "municipio", "departamento", "tipo_territorio"):
        panel[columna + "_catalogo_actual"] = panel["divipola__" + columna].copy()
    panel["estado_catalogo_actual"] = panel["divipola__estado_catalogo"].fillna("sin_coincidencia")
    for nombre in ("poblacion", "internet"):
        columna = "departamento_coincide_" + nombre
        panel[columna] = _comparar_departamentos(panel, nombre, "coincidencia_" + nombre)
    panel["departamento_coincide_catalogo_actual"] = _comparar_departamentos(panel, "divipola", "coincidencia_catalogo_actual")
    incompatibles = pd.Series(False, index=panel.index, dtype="boolean")
    departamentos_desconocidos = pd.Series(False, index=panel.index, dtype="boolean")
    for fuente, coincide, comparacion in (
        ("poblacion", "coincidencia_poblacion", "departamento_coincide_poblacion"),
        ("internet", "coincidencia_internet", "departamento_coincide_internet"),
        ("divipola", "coincidencia_catalogo_actual", "departamento_coincide_catalogo_actual"),
    ):
        # Desconocido no equivale a contradictorio: ambos requieren diagnostico.
        incompatibles |= panel[coincide] & panel[comparacion].eq(False).fillna(False)
        departamentos_desconocidos |= panel[coincide] & panel[comparacion].isna()
    panel["departamento_inconsistente_entre_fuentes"] = incompatibles
    panel["departamento_desconocido_en_coincidencias"] = departamentos_desconocidos

    # Las ausencias se distinguen de reportes existentes con un valor invalido.
    panel.loc[~panel["coincidencia_poblacion"], "estado_poblacion"] = "sin_coincidencia"
    panel.loc[~panel["coincidencia_internet"], "estado_internet"] = "sin_reporte_t4"
    for bandera in ("poblacion_para_ratios_utilizable", "accesos_para_indicadores_utilizables", "denominador_positivo"):
        panel[bandera] = panel[bandera].fillna(False).astype("boolean")
    if "trimestre_referencia" not in panel or (
        panel.loc[panel["coincidencia_internet"], "trimestre_referencia"].ne(4).fillna(True).any()
    ):
        raise ValueError("Una observacion anual de internet debe tener referencia T4.")

    historicos = set(configuracion["sources"]["population"]["territorial_review_codes"])
    historicos.update(configuracion["sources"]["internet_access"]["territorial_review_codes"])
    panel["revision_territorial_pendiente"] = panel["codigo_municipio"].isin(historicos).astype("boolean")
    panel["estado_homologacion"] = pd.Series("pendiente_revision", index=panel.index, dtype="string")
    panel["motivo_homologacion"] = pd.Series("vigencia_temporal_no_acreditada", index=panel.index, dtype="string")
    panel.loc[panel["revision_territorial_pendiente"], "motivo_homologacion"] = "caso_historico_pendiente"
    panel.loc[panel["estado_catalogo_actual"].ne("disponible"), "motivo_homologacion"] = "metadatos_catalogo_pendientes"
    panel.loc[departamentos_desconocidos, "motivo_homologacion"] = "departamentos_no_documentados"
    panel.loc[incompatibles, "motivo_homologacion"] = "departamentos_incompatibles"
    panel.loc[~panel["coincidencia_catalogo_actual"], "motivo_homologacion"] = "sin_coincidencia_catalogo"
    panel["evidencia_homologacion"] = pd.Series(pd.NA, index=panel.index, dtype="string")
    panel["vigencia_desde"] = pd.Series(pd.NA, index=panel.index, dtype="Int64")
    panel["vigencia_hasta"] = pd.Series(pd.NA, index=panel.index, dtype="Int64")
    # La categoria del archivo actual se conserva aparte; no se aplica al pasado.
    panel["tipo_territorio"] = pd.Series("no_resuelto", index=panel.index, dtype="string")

    # Las copias anuales verificadas acreditan filas concretas sin interpolar.
    # Si no se proporciona evidencia, se conserva el comportamiento exploratorio.
    panel = aplicar_evidencia_territorial(panel, evidencia)

    consistente = _consistencia_poblacional(panel) & panel["poblacion_consistente"].fillna(False)
    for columna in configuracion["quality"]["critical_columns"]:
        valor = panel[columna]
        presentes = valor.notna() & ~valor.isin([float("inf"), float("-inf")])
        if columna in ("cobertura_neta", "desercion", "reprobacion"):
            uso = panel["estado_" + columna].eq("disponible")
            # La ficha MEN admite cobertura neta >100; no extender ese criterio
            # a desercion o reprobacion, que mantienen su restriccion de rango.
            if columna != "cobertura_neta":
                uso &= valor.le(100)
        elif columna.startswith("poblacion_"):
            uso = panel["estado_poblacion"].eq("disponible") & consistente
        else:
            uso = panel["estado_internet"].eq("disponible") & panel["accesos_para_indicadores_utilizables"]
        panel[columna + "_utilizable_fuente"] = (uso & presentes & valor.ge(0)).fillna(False).astype("boolean")
        panel[columna + "_utilizable_panel"] = (
            panel[columna + "_utilizable_fuente"]
            & panel["estado_homologacion"].isin(["resuelto_catalogo", "resuelto_regla_historica"])
        ).astype("boolean")

    diagnosticos = {"filas_universo_educativo": cantidad, "filas_despues_uniones": len(panel),
                   "llaves_duplicadas": int(panel.duplicated(LLAVE).sum())}
    llaves_men = pd.MultiIndex.from_frame(tablas["educacion"][LLAVE])
    for nombre in ("poblacion", "internet"):
        originales = tablas[nombre]
        extras = originales.loc[~pd.MultiIndex.from_frame(originales[LLAVE]).isin(llaves_men)]
        coincidencia = panel["coincidencia_" + nombre]
        diagnosticos[nombre] = {
            "filas_silver": len(originales), "coincidencias": int(coincidencia.sum()),
            "sin_coincidencia": int((~coincidencia).sum()),
            "filas_extras_fuera_universo": len(extras), "extras_fuera_universo": _registros_json(extras),
            "filas_men_sin_coincidencia": _registros_json(panel.loc[~coincidencia, LLAVE + ["municipio", "departamento"]]),
            "departamentos_incompatibles": int((coincidencia & panel["departamento_coincide_" + nombre].eq(False).fillna(False)).sum()),
            "departamentos_desconocidos": int((coincidencia & panel["departamento_coincide_" + nombre].isna()).sum()),
        }
    actual = panel["coincidencia_catalogo_actual"]
    diagnosticos["divipola"] = {
        "filas_silver": len(tablas["divipola"]), "coincidencias": int(actual.sum()),
        "sin_coincidencia": int((~actual).sum()),
        "porcentaje_coincidencia_actual": int(actual.sum()) / cantidad * 100,
        "filas_men_sin_coincidencia": _registros_json(panel.loc[~actual, LLAVE + ["municipio", "departamento"]]),
        "departamentos_incompatibles": int((actual & panel["departamento_coincide_catalogo_actual"].eq(False).fillna(False)).sum()),
        "departamentos_desconocidos": int((actual & panel["departamento_coincide_catalogo_actual"].isna()).sum()),
        "codigos_catalogo_fuera_universo": sorted(set(tablas["divipola"]["codigo_municipio"]) - set(panel["codigo_municipio"])),
        "tipos_catalogo_actual_en_panel": {str(tipo): int(cantidad_tipo) for tipo, cantidad_tipo in panel["tipo_territorio_catalogo_actual"].value_counts().items()},
    }
    # El reporte conserva referencias y conteos, no miles de atributos repetidos.
    evidencia_publicable = {clave: valor for clave, valor in evidencia.items() if clave != "catalogos_anuales"}
    evidencia_publicable["catalogos_anuales"] = [
        {clave: valor for clave, valor in catalogo.items() if clave != "registros"}
        for catalogo in evidencia.get("catalogos_anuales", [])
    ]
    return panel, evaluar_panel(panel, diagnosticos, configuracion, evidencia_publicable)
