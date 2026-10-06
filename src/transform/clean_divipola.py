"""Preparar el catalogo territorial sin inferir correspondencias historicas."""

import copy
import logging
import re
import unicodedata
from typing import Any, Dict, Mapping, Tuple

import pandas as pd


LOGGER = logging.getLogger(__name__)

RENOMBRADO = {
    "Código Municipio": "codigo_municipio", "Nombre Municipio": "municipio",
    "Código Departamento": "codigo_departamento", "Nombre Departamento": "departamento",
    "Tipo: Municipio / Isla / Área no municipalizada": "tipo_territorio",
    "longitud": "longitud", "Latitud": "latitud",
}
OBLIGATORIAS = set(RENOMBRADO) - {"longitud", "Latitud"}
TIPOS = {
    "municipio": "municipio", "area no municipalizada": "area_no_municipalizada",
    "isla": "isla",
}


def _texto_comparable(texto: str) -> str:
    """Comparar etiquetas sin tildes, diferencias de mayusculas o espacios."""
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return " ".join(texto.lower().split())


def _nombre_columna(nombre: str) -> str:
    """Conservar campos nuevos bajo un encabezado uniforme y comprobable."""
    return re.sub(r"[^a-z0-9]+", "_", _texto_comparable(nombre)).strip("_")


def _normalizar_codigo(serie: pd.Series, longitud: int) -> pd.Series:
    """Completar ceros solo en codigos numericos no nacionales y de longitud valida."""
    valido = serie.str.fullmatch(r"[0-9]{1,%s}" % longitud, na=False)
    valido = valido & ~serie.str.fullmatch(r"0+", na=False)
    return serie.where(valido).str.zfill(longitud)


def _convertir_coordenada(textos: pd.Series, limite: int) -> Tuple[pd.Series, pd.Series]:
    """Leer coma o punto decimal en coordenadas y marcar valores no utilizables."""
    # La coma decimal se cambia SOLO en estos campos, nunca en nombres o codigos.
    formato = textos.str.fullmatch(r"[+-]?[0-9]+(?:[.,][0-9]+)?", na=False)
    valores = pd.to_numeric(
        textos.where(formato).str.replace(",", ".", regex=False), errors="coerce"
    ).astype("Float64")
    estados = pd.Series("disponible", index=textos.index, dtype="string")
    estados.loc[textos.isna()] = "faltante"
    estados.loc[textos.notna() & valores.isna()] = "no_numerico"
    # Coordenadas infinitas o fuera de rango no permiten ubicar un territorio.
    infinitos = textos.str.lower().isin(["inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"])
    fuera_rango = valores.abs().gt(limite).fillna(False)
    estados.loc[infinitos | fuera_rango] = "no_utilizable"
    valores = valores.mask(estados.ne("disponible"))
    return valores, estados


def limpiar_divipola(
    datos_originales: pd.DataFrame, configuracion: Mapping[str, Any]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Devolver ``(catalogo, reporte)`` con una fila por codigo municipal.

    Este catalogo no tiene anio. Su limpieza no modifica las tablas educativas
    o poblacionales ni declara resuelta la identidad territorial de un panel.
    """
    proceso = configuracion["processing"]
    calidad = configuracion["quality"]
    if proceso["impute_missing_as_zero"]:
        raise ValueError("El contrato no permite imputar ceros en DIVIPOLA.")
    if not proceso["include_non_municipal_areas"]:
        raise ValueError("El catalogo debe conservar las areas no municipalizadas.")
    if not calidad["fail_on_missing_key"] or not calidad["fail_on_duplicate_key"]:
        raise ValueError("La llave DIVIPOLA incompleta o duplicada debe detener la etapa.")

    # Una copia evita alterar la fuente extraida o una tabla del notebook.
    datos = datos_originales.copy(deep=True).reset_index(drop=True)
    if datos.columns.duplicated().any():
        raise ValueError("El catalogo repite encabezados.")
    faltantes = sorted(OBLIGATORIAS - set(datos.columns))
    if faltantes:
        raise ValueError("Faltan columnas para limpiar DIVIPOLA: {}".format(faltantes))
    renombrado = {nombre: RENOMBRADO.get(nombre, _nombre_columna(nombre)) for nombre in datos.columns}
    if len(set(renombrado.values())) != len(renombrado):
        raise ValueError("Dos encabezados DIVIPOLA producen el mismo nombre normalizado.")
    datos = datos.rename(columns=renombrado)
    columnas_fuente = list(datos.columns)
    campos_originales = ["codigo_municipio", "municipio", "codigo_departamento",
                         "departamento", "tipo_territorio"]
    coordenadas = [nombre for nombre in ("longitud", "latitud") if nombre in columnas_fuente]
    reservadas = {
        "registro_origen", "departamento_inconsistente", "metadatos_incompletos",
        "departamento_nombre_inconsistente", "tipo_no_resuelto", "estado_catalogo",
        "coordenadas_utilizables", "estado_longitud", "estado_latitud",
    }.union(nombre + "_original" for nombre in campos_originales + ["longitud", "latitud"])
    if reservadas.intersection(columnas_fuente):
        raise ValueError("La fuente usa columnas reservadas para trazabilidad DIVIPOLA.")
    if datos.empty:
        raise ValueError("No hay territorios en el catalogo DIVIPOLA.")

    # El ordinal identifica el registro CSV, no una linea fisica: puede haber
    # comas o saltos de linea dentro de una celda entrecomillada.
    datos["registro_origen"] = pd.Series(range(1, len(datos) + 1), dtype="Int64")
    for nombre in campos_originales + coordenadas:
        datos[nombre + "_original"] = datos[nombre].astype("string")
    for nombre in columnas_fuente:
        datos[nombre] = datos[nombre].astype("string").str.strip().replace("", pd.NA)
    datos["codigo_municipio"] = _normalizar_codigo(
        datos["codigo_municipio"], proceso["municipality_code_length"]
    )
    datos["codigo_departamento"] = _normalizar_codigo(
        datos["codigo_departamento"], proceso["department_code_length"]
    )
    if datos["codigo_municipio"].isna().any():
        raise ValueError("Hay codigos municipales incompletos o con formato invalido.")
    # DIVIPOLA tiene una fila por territorio, a diferencia de las fuentes anuales.
    if datos["codigo_municipio"].duplicated(keep=False).any():
        raise ValueError("Codigo municipal duplicado; no se eliminan registros del catalogo.")

    # Comparar etiquetas no altera sus originales ni los nombres territoriales.
    tipos_comparables = datos["tipo_territorio"].map(
        lambda valor: None if pd.isna(valor) else _texto_comparable(valor)
    )
    datos["tipo_territorio"] = tipos_comparables.map(TIPOS).fillna("no_resuelto").astype("string")
    datos["tipo_no_resuelto"] = datos["tipo_territorio"].eq("no_resuelto")
    datos["departamento_inconsistente"] = (
        datos["codigo_municipio"].str[:proceso["department_code_length"]]
        .ne(datos["codigo_departamento"]).fillna(True)
    )
    datos["metadatos_incompletos"] = datos[["codigo_departamento", "municipio", "departamento"]].isna().any(axis=1)
    # Si un mismo codigo departamental tiene nombres contradictorios, no damos
    # por valido automaticamente ninguno. Ignoramos solo diferencias de escritura.
    nombres_departamento = datos["departamento"].map(
        lambda valor: None if pd.isna(valor) else _texto_comparable(valor)
    )
    pares = pd.DataFrame({"codigo": datos["codigo_departamento"], "nombre": nombres_departamento})
    conflicto_nombres = pares.groupby("codigo", dropna=False)["nombre"].transform("nunique").gt(1)
    datos["departamento_nombre_inconsistente"] = conflicto_nombres & datos["codigo_departamento"].notna()
    pendientes = (datos["departamento_inconsistente"] | datos["metadatos_incompletos"]
                  | datos["departamento_nombre_inconsistente"] | datos["tipo_no_resuelto"])
    datos["estado_catalogo"] = pd.Series("disponible", index=datos.index, dtype="string")
    datos.loc[pendientes, "estado_catalogo"] = "pendiente_revision"

    # Las coordenadas son auxiliares para ubicacion. No son la llave de una union
    # ni una condicion para reconocer el codigo y el tipo territorial del catalogo.
    for nombre in coordenadas:
        datos[nombre], datos["estado_" + nombre] = _convertir_coordenada(
            datos[nombre], limite=180 if nombre == "longitud" else 90
        )
    datos["coordenadas_utilizables"] = False
    if len(coordenadas) == 2:
        datos["coordenadas_utilizables"] = (
            datos["estado_longitud"].eq("disponible") & datos["estado_latitud"].eq("disponible")
        )

    # El reporte acredita controles del archivo disponible; no inventa fecha
    # de vigencia, anios ni una regla de homologacion para territorios historicos.
    desconocidas = sorted(set(columnas_fuente) - set(RENOMBRADO.values()))
    reporte = {
        "filas_entrada": len(datos_originales), "filas_salida": len(datos),
        "claves_duplicadas": 0, "columnas_renombradas": renombrado,
        "origen_csv": copy.deepcopy(datos_originales.attrs.get("origen_csv", {})),
        "departamentos_distintos": int(datos["codigo_departamento"].nunique()),
        "departamentos_inconsistentes": int(datos["departamento_inconsistente"].sum()),
        "metadatos_incompletos": int(datos["metadatos_incompletos"].sum()),
        "filas_con_nombre_departamental_inconsistente": int(datos["departamento_nombre_inconsistente"].sum()),
        "tipos_territorio": {str(tipo): int(cantidad) for tipo, cantidad in datos["tipo_territorio"].value_counts().items()},
        "tipos_no_resueltos": int(datos["tipo_no_resuelto"].sum()),
        "estados_catalogo": {str(estado): int(cantidad) for estado, cantidad in datos["estado_catalogo"].value_counts().items()},
        "campos_coordenadas_presentes": coordenadas,
        "filas_con_coordenadas_utilizables": int(datos["coordenadas_utilizables"].sum()),
        "estados_coordenadas": {
            nombre: {str(estado): int(cantidad) for estado, cantidad in datos["estado_" + nombre].value_counts().items()}
            for nombre in coordenadas
        },
        "rangos_coordenadas": {
            nombre: {"min": None if datos[nombre].dropna().empty else float(datos[nombre].min()),
                     "max": None if datos[nombre].dropna().empty else float(datos[nombre].max())}
            for nombre in coordenadas
        },
        "columnas_nuevas_no_tipificadas": desconocidas,
        "faltantes_campos_territoriales": {
            nombre: int(datos[nombre].isna().sum()) for nombre in ("codigo_municipio", "codigo_departamento", "municipio", "departamento")
        },
        "vigencia_historica_verificada": False,
    }
    primeras = ["codigo_municipio", "municipio", "codigo_departamento", "departamento", "tipo_territorio"]
    datos = datos[primeras + [nombre for nombre in datos.columns if nombre not in primeras]]
    LOGGER.info("DIVIPOLA preparado: %s territorios, %s pendientes en el catalogo", len(datos), int(pendientes.sum()))
    return datos, reporte
