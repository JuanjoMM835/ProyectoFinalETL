"""Validar bloques de internet y preparar accesos anuales de T4."""

import copy
import json
import logging
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Tuple

import pandas as pd


LOGGER = logging.getLogger(__name__)
COLUMNAS = [
    "ANNO", "TRIMESTRE", "ID_EMPRESA", "EMPRESA", "ID_MUNICIPIO", "MUNICIPIO",
    "ID_DEPARTAMENTO", "DEPARTAMENTO", "ID_SEGMENTO", "SEGMENTO",
    "VELOCIDAD_EFECTIVA_DOWNSTREAM", "VELOCIDAD_EFECTIVA_UPSTREAM",
    "ID_TECNOLOGIA", "TECNOLOGIA", "ACCESOS",
]
VELOCIDADES = ["VELOCIDAD_EFECTIVA_DOWNSTREAM", "VELOCIDAD_EFECTIVA_UPSTREAM"]
MAX_ENTERO = 9223372036854775807


def _normalizar_codigo(textos: pd.Series, longitud: int) -> pd.Series:
    """Conservar como texto los codigos territoriales validos, con ceros iniciales."""
    valido = textos.str.fullmatch(r"[0-9]{1,%s}" % longitud, na=False)
    valido = valido & ~textos.str.fullmatch(r"0+", na=False)
    return textos.where(valido).str.zfill(longitud)


def _clave_velocidad(texto: str) -> str:
    """Identificar el mismo numero escrito como 2, 2.0 o 2,0 sin redondearlo."""
    try:
        valor = Decimal(texto.replace(",", "."))
        if not valor.is_finite():
            return "texto:" + texto
        if valor == 0:
            return "0"
        # format 'f' conserva los digitos: no usamos float para comparar llaves.
        salida = format(valor, "f")
        return salida.rstrip("0").rstrip(".") if "." in salida else salida
    except InvalidOperation:
        return "texto:" + texto


def _accesos_enteros(textos: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Aceptar conteos enteros no negativos, preservando faltantes y precision."""
    conversiones = {}
    # Decimal compara el texto exacto: un float podria redondear una fraccion
    # pequena o un entero grande. Convertimos cada texto distinto una sola vez.
    for texto in textos.dropna().unique():
        entero = None
        try:
            numero = Decimal(str(texto))
            if (numero.is_finite() and 0 <= numero <= MAX_ENTERO
                    and numero == numero.to_integral_value()):
                entero = int(numero)
        except InvalidOperation:
            pass
        conversiones[texto] = entero
    # Construir directamente Int64 evita que una lista con None pase por float.
    valores = [None if pd.isna(texto) else conversiones[texto] for texto in textos]
    numeros = pd.Series(pd.array(valores, dtype="Int64"), index=textos.index)
    return numeros, numeros.notna()


def limpiar_internet(
    bloques: Iterable[pd.DataFrame], configuracion: Mapping[str, Any]
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Devolver ``(internet_anual, reporte)`` sin escribir Silver ni Gold.

    Los bloques se consumen una sola vez. La tabla final contiene solo los
    territorios-anio con un reporte T4; las ausencias se marcaran al integrar.
    """
    proceso, calidad = configuracion["processing"], configuracion["quality"]
    fuente = configuracion["sources"]["internet_access"]
    if proceso["internet_quarter"] != 4 or proceso["allow_quarter_fallback"]:
        raise ValueError("El contrato exige T4, sin sustituirlo por otro trimestre.")
    if proceso["impute_missing_as_zero"] or not proceso["exclude_national_records"]:
        raise ValueError("Se conservan faltantes y se separan los registros nacionales.")
    if not proceso["include_non_municipal_areas"]:
        raise ValueError("Deben conservarse las areas no municipalizadas.")
    if not calidad["fail_on_missing_key"] or not calidad["fail_on_duplicate_key"]:
        raise ValueError("Las llaves incompletas o duplicadas deben detener esta etapa.")
    if proceso["primary_key"] != ["codigo_municipio", "anio"]:
        raise ValueError("La llave anual acordada es codigo_municipio + anio.")
    if configuracion["indicators"]["weighted_speed_enabled"] or configuracion["indicators"]["fiber_share_enabled"]:
        raise ValueError("Velocidad ponderada y fibra todavia no estan implementadas.")
    inicio, fin = proceso["year_start"], proceso["year_end"]
    if type(inicio) is not int or type(fin) is not int or inicio > fin:
        raise ValueError("El periodo requiere anios enteros en orden valido.")
    historicos = set(fuente["territorial_review_codes"])
    segmentos_conocidos = set(fuente["known_segment_ids"])
    segmentos_revision = set(fuente["review_segment_ids"])

    # Acumulamos solo resumenes municipales, etiquetas y controles pequenos.
    # No concatenamos los millones de filas del CSV original.
    acumulados: Dict[Tuple[str, int], Dict[str, Any]] = {}
    contadores = Counter()
    faltantes = Counter()
    segmentos = Counter()
    tecnologias = Counter()
    columnas_nuevas = set()
    origen: Dict[str, Any] = {}
    ejemplos_invalidos = []
    ejemplos_nacionales = []
    cache_velocidades: Dict[str, str] = {}

    # SQLite guarda llaves EXACTAS en disco temporal, no una huella aproximada.
    # Su indice UNIQUE detecta repeticiones entre bloques con memoria contenida.
    # No es una base de datos del proyecto: se cierra y elimina al salir.
    with tempfile.TemporaryDirectory(prefix="etl_internet_llaves_") as temporal:
        with closing(sqlite3.connect(str(Path(temporal) / "control.sqlite"))) as control:
            control.execute("PRAGMA journal_mode=MEMORY")
            control.execute("PRAGMA synchronous=OFF")
            control.execute("CREATE TABLE reportes (clave TEXT PRIMARY KEY, registro INTEGER NOT NULL) WITHOUT ROWID")
            for bloque in bloques:
                if bloque.empty:
                    continue
                contadores["bloques_leidos"] += 1
                if bloque.columns.duplicated().any():
                    raise ValueError("El bloque de internet repite encabezados.")
                ausentes = sorted(set(COLUMNAS) - set(bloque.columns))
                if ausentes:
                    raise ValueError("Faltan columnas de internet: {}".format(ausentes))
                columnas_nuevas.update(set(bloque.columns) - set(COLUMNAS))
                if not origen and bloque.attrs.get("origen_csv"):
                    origen = copy.deepcopy(bloque.attrs["origen_csv"])
                    origen.pop("bloque", None)
                    origen.pop("registro_inicial", None)
                # Cada bloque se copia: la limpieza no altera tablas del llamador.
                datos = bloque[COLUMNAS].copy(deep=True).reset_index(drop=True)
                originales = datos[["ID_MUNICIPIO", "MUNICIPIO", "ID_DEPARTAMENTO", "DEPARTAMENTO", "ACCESOS"]].copy()
                primero = contadores["filas_entrada"] + 1
                datos["registro_origen"] = pd.Series(range(primero, primero + len(datos)), dtype="Int64")
                contadores["filas_entrada"] += len(datos)
                for nombre in COLUMNAS:
                    datos[nombre] = datos[nombre].astype("string").str.strip().replace("", pd.NA)
                faltantes.update(datos[COLUMNAS].isna().sum().to_dict())

                # Los periodos tambien deben ser enteros exactos, sin redondeo.
                anios, _ = _accesos_enteros(datos["ANNO"])
                trimestres, _ = _accesos_enteros(datos["TRIMESTRE"])
                periodos_invalidos = (
                    anios.isna() | anios.le(0) | ~trimestres.isin([1, 2, 3, 4])
                ).fillna(True)
                if periodos_invalidos.any():
                    raise ValueError("Hay anios o trimestres invalidos en registros: {}".format(
                        datos.loc[periodos_invalidos, "registro_origen"].tolist()[:10]))
                datos["anio"] = anios.astype("Int64")
                datos["trimestre"] = trimestres.astype("Int64")

                # Codigo cero requiere evidencia nacional. Colombia, Huila,
                # tiene un codigo municipal propio y no cumple esta condicion.
                nacional = datos["ID_MUNICIPIO"].str.fullmatch(r"0+", na=False)
                departamento_nacional = datos["DEPARTAMENTO"].str.upper().isin(["COLOMBIA", "NACIONAL"])
                nombre_nacional = (datos["MUNICIPIO"].str.upper().eq("NACIONAL") | (
                    datos["MUNICIPIO"].str.upper().eq("COLOMBIA") & departamento_nacional)).fillna(False)
                if ((nacional != nombre_nacional).any() or (nacional & ~departamento_nacional).any()
                        or (nacional & ~datos["ID_DEPARTAMENTO"].str.fullmatch(r"0+", na=False)).any()):
                    raise ValueError("Codigo y nombres no concuerdan al identificar registros nacionales.")
                datos["codigo_municipio"] = _normalizar_codigo(datos["ID_MUNICIPIO"], proceso["municipality_code_length"])
                datos["codigo_departamento"] = _normalizar_codigo(datos["ID_DEPARTAMENTO"], proceso["department_code_length"])
                if (datos["codigo_municipio"].isna() & ~nacional).any():
                    raise ValueError("Hay codigos municipales incompletos o con formato invalido.")
                for nombre in ("ID_EMPRESA", "ID_SEGMENTO", "ID_TECNOLOGIA"):
                    if not datos[nombre].str.fullmatch(r"[0-9]+", na=False).all():
                        raise ValueError("Hay identificadores de reporte incompletos o invalidos: {}".format(nombre))
                contadores["filas_nacionales_globales"] += int(nacional.sum())
                if len(ejemplos_nacionales) < 10:
                    ejemplos_nacionales.extend(datos.loc[nacional, ["registro_origen", "ANNO", "TRIMESTRE", "ID_MUNICIPIO", "MUNICIPIO"]]
                                               .astype(object).to_dict("records")[:10 - len(ejemplos_nacionales)])

                valores, validos = _accesos_enteros(datos["ACCESOS"])
                datos["accesos"] = valores
                contadores["accesos_no_utilizables_globales"] += int((~validos).sum())
                contadores["accesos_cero_globales"] += int(valores.eq(0).sum())
                contadores["tecnologia_na_global"] += int(datos["TECNOLOGIA"].eq("NA").sum())
                metadatos_velocidad = pd.Series(False, index=datos.index)
                for nombre in VELOCIDADES:
                    numeros = pd.to_numeric(datos[nombre].str.replace(",", ".", regex=False), errors="coerce")
                    no_finito = numeros.isin([float("inf"), float("-inf")])
                    mala = (numeros.isna() | no_finito | numeros.lt(0)).fillna(True)
                    metadatos_velocidad |= mala
                    contadores[nombre + "_no_utilizables"] += int(mala.sum())
                    contadores[nombre + "_ceros"] += int(numeros.eq(0).sum())
                    for texto in datos[nombre].dropna().unique():
                        if texto not in cache_velocidades:
                            cache_velocidades[texto] = _clave_velocidad(texto)
                    datos["clave_" + nombre] = datos[nombre].map(cache_velocidades).fillna("faltante:")

                # La llave de reporte incluye categorias y velocidades, pero NO
                # accesos: dos cantidades para el mismo detalle son ambiguas.
                clave = datos[["anio", "trimestre", "ID_EMPRESA", "codigo_municipio", "ID_SEGMENTO", "ID_TECNOLOGIA"]].astype("string")
                clave.loc[nacional, "codigo_municipio"] = "00000"
                for nombre in VELOCIDADES:
                    clave[nombre] = datos["clave_" + nombre]
                filas_sql = ((json.dumps(list(fila), ensure_ascii=False, separators=(",", ":")), int(registro))
                             for fila, registro in zip(clave.itertuples(index=False, name=None), datos["registro_origen"]))
                try:
                    with control:
                        control.executemany("INSERT INTO reportes (clave, registro) VALUES (?, ?)", filas_sql)
                except sqlite3.IntegrityError as error:
                    raise ValueError("Llave de reporte duplicada entre registros o bloques; no se suman ni eliminan filas.") from error

                en_periodo = datos["anio"].between(inicio, fin)
                es_t4 = datos["trimestre"].eq(4)
                seleccion = en_periodo & es_t4 & ~nacional
                contadores["filas_fuera_periodo"] += int((~en_periodo).sum())
                contadores["filas_otros_trimestres_periodo"] += int((en_periodo & ~es_t4).sum())
                contadores["filas_nacionales_t4_separados"] += int((en_periodo & es_t4 & nacional).sum())
                contadores["filas_seleccionadas"] += int(seleccion.sum())
                contadores["tecnologia_na_seleccionada"] += int((seleccion & datos["TECNOLOGIA"].eq("NA")).sum())
                contadores["accesos_cero_seleccionados"] += int(valores.loc[seleccion].eq(0).sum())

                # No mezclamos categorias que se declaren totales con su detalle.
                totales = datos["SEGMENTO"].str.contains(r"(?i)\btotal(?:es)?\b", na=False) | datos["TECNOLOGIA"].str.contains(r"(?i)\btotal(?:es)?\b", na=False)
                if (seleccion & totales).any():
                    raise ValueError("Una categoria Total requiere revisar superposicion antes de agregar.")
                datos["departamento_inconsistente"] = datos["codigo_municipio"].str[:proceso["department_code_length"]].ne(datos["codigo_departamento"]).fillna(True)
                datos["metadatos_reporte_pendientes"] = metadatos_velocidad | datos[["EMPRESA", "MUNICIPIO", "DEPARTAMENTO", "SEGMENTO", "TECNOLOGIA"]].isna().any(axis=1)
                datos["segmento_pendiente_revision"] = datos["ID_SEGMENTO"].isin(segmentos_revision) | ~datos["ID_SEGMENTO"].isin(segmentos_conocidos)
                datos["acceso_no_utilizable"] = ~validos
                for nombre in originales.columns:
                    datos["original_" + nombre] = originales[nombre].astype("string")
                malas = seleccion & ~validos
                if len(ejemplos_invalidos) < 10:
                    ejemplos_invalidos.extend(datos.loc[malas, ["registro_origen", "ANNO", "ID_MUNICIPIO", "original_ACCESOS"]]
                                              .astype(object).where(datos.loc[malas, ["registro_origen", "ANNO", "ID_MUNICIPIO", "original_ACCESOS"]].notna(), None)
                                              .to_dict("records")[:10 - len(ejemplos_invalidos)])
                campos = ["codigo_municipio", "anio", "codigo_departamento", "accesos", "registro_origen",
                          "departamento_inconsistente", "metadatos_reporte_pendientes", "segmento_pendiente_revision",
                          "original_ID_MUNICIPIO", "original_MUNICIPIO", "original_ID_DEPARTAMENTO", "original_DEPARTAMENTO",
                          "ID_SEGMENTO", "SEGMENTO", "ID_TECNOLOGIA", "TECNOLOGIA"]
                for fila in datos.loc[seleccion, campos].itertuples(index=False, name=None):
                    codigo, anio, departamento, acceso, registro, inconsistente, meta, segmento_pendiente, cm, nm, cd, nd, segid, seg, tecid, tec = fila
                    llave = (codigo, int(anio))
                    if llave not in acumulados:
                        acumulados[llave] = {"suma": 0, "validos": 0, "invalidos": 0, "registros": 0,
                                            "min": int(registro), "max": int(registro), "departamentos": set(),
                                            "codigos_originales": set(), "nombres_originales": set(),
                                            "departamentos_originales": set(), "nombres_departamentos": set(),
                                            "segmentos": set(), "tecnologias": set(), "inconsistente": False,
                                            "meta": False, "segmento_pendiente": False}
                    grupo = acumulados[llave]
                    grupo["registros"] += 1
                    grupo["max"] = int(registro)
                    if pd.isna(acceso):
                        grupo["invalidos"] += 1
                    else:
                        # int de Python suma exactamente, sin overflow silencioso.
                        grupo["suma"] += int(acceso)
                        grupo["validos"] += 1
                    for valor, destino in ((departamento, "departamentos"), (cm, "codigos_originales"),
                                           (nm, "nombres_originales"), (cd, "departamentos_originales"), (nd, "nombres_departamentos")):
                        if not pd.isna(valor):
                            grupo[destino].add(str(valor))
                    par_segmento = (str(segid), None if pd.isna(seg) else str(seg))
                    par_tecnologia = (str(tecid), None if pd.isna(tec) else str(tec))
                    grupo["segmentos"].add(par_segmento)
                    grupo["tecnologias"].add(par_tecnologia)
                    segmentos[par_segmento] += 1
                    tecnologias[par_tecnologia] += 1
                    grupo["inconsistente"] |= bool(inconsistente)
                    grupo["meta"] |= bool(meta)
                    grupo["segmento_pendiente"] |= bool(segmento_pendiente)
                if contadores["bloques_leidos"] % 5 == 0:
                    LOGGER.info("Internet: %s bloques, %s filas revisadas", contadores["bloques_leidos"], contadores["filas_entrada"])

    if contadores["filas_entrada"] == 0:
        raise ValueError("No hay bloques con registros de internet.")
    filas = []
    for (codigo, anio), grupo in sorted(acumulados.items()):
        if grupo["suma"] > MAX_ENTERO:
            raise ValueError("La suma de accesos excede el rango de Int64.")
        historico = codigo in historicos
        pendiente = historico or grupo["inconsistente"] or grupo["meta"] or grupo["segmento_pendiente"]
        estado = "no_utilizable" if grupo["invalidos"] else ("pendiente_revision" if pendiente else "disponible")
        nombres = sorted(grupo["nombres_originales"])
        departamentos = sorted(grupo["nombres_departamentos"])
        # El nombre mostrado es representativo. Conservamos todas las variantes
        # y la futura integracion usara el codigo, nunca similitud de nombres.
        filas.append({
            "codigo_municipio": codigo, "anio": anio,
            "codigo_departamento": next(iter(grupo["departamentos"])) if len(grupo["departamentos"]) == 1 else None,
            "municipio": nombres[0].strip() if nombres else None,
            "departamento": departamentos[0].strip() if departamentos else None,
            "accesos_t4": grupo["suma"] if not grupo["invalidos"] else None,
            "accesos_validos_parcial": grupo["suma"] if grupo["validos"] else None,
            "trimestre_referencia": 4, "registros_fuente": grupo["registros"],
            "registros_accesos_no_utilizables": grupo["invalidos"],
            "registro_origen_min": grupo["min"], "registro_origen_max": grupo["max"],
            "revision_territorial_pendiente": historico, "departamento_inconsistente": grupo["inconsistente"],
            "metadatos_reporte_pendientes": grupo["meta"], "segmento_pendiente_revision": grupo["segmento_pendiente"],
            "estado_internet": estado, "accesos_para_indicadores_utilizables": estado == "disponible",
            "estado_homologacion": "pendiente_revision",
            "codigos_municipio_originales": json.dumps(sorted(grupo["codigos_originales"]), ensure_ascii=False),
            "nombres_municipio_originales": json.dumps(nombres, ensure_ascii=False),
            "codigos_departamento_originales": json.dumps(sorted(grupo["departamentos_originales"]), ensure_ascii=False),
            "nombres_departamento_originales": json.dumps(departamentos, ensure_ascii=False),
            "segmentos_originales": json.dumps(sorted(grupo["segmentos"], key=lambda par: (par[0], par[1] or "")), ensure_ascii=False),
            "tecnologias_originales": json.dumps(sorted(grupo["tecnologias"], key=lambda par: (par[0], par[1] or "")), ensure_ascii=False),
        })
    tipos = {"codigo_municipio": "string", "anio": "Int64", "codigo_departamento": "string",
             "municipio": "string", "departamento": "string", "accesos_t4": "Int64", "accesos_validos_parcial": "Int64",
             "trimestre_referencia": "Int64", "registros_fuente": "Int64", "registros_accesos_no_utilizables": "Int64",
             "registro_origen_min": "Int64", "registro_origen_max": "Int64", "revision_territorial_pendiente": "boolean",
             "departamento_inconsistente": "boolean", "metadatos_reporte_pendientes": "boolean", "segmento_pendiente_revision": "boolean",
             "estado_internet": "string", "accesos_para_indicadores_utilizables": "boolean", "estado_homologacion": "string",
             "codigos_municipio_originales": "string", "nombres_municipio_originales": "string", "codigos_departamento_originales": "string",
             "nombres_departamento_originales": "string", "segmentos_originales": "string", "tecnologias_originales": "string"}
    tabla = pd.DataFrame(filas).reindex(columns=list(tipos)).astype(tipos)
    # Python None representa faltante en JSON; la tabla mantiene tipos anulables.
    resumen_anual = [{"anio": int(anio), "territorios": int(len(grupo)),
                      "accesos": None if grupo["accesos_t4"].isna().any() else sum(int(valor) for valor in grupo["accesos_t4"]),
                      "registros_fuente": int(grupo["registros_fuente"].sum())}
                     for anio, grupo in tabla.groupby("anio", sort=True)]
    nombres_contadores = ["filas_entrada", "bloques_leidos", "filas_fuera_periodo", "filas_otros_trimestres_periodo",
                         "filas_nacionales_globales", "filas_nacionales_t4_separados", "filas_seleccionadas",
                         "accesos_no_utilizables_globales", "accesos_cero_globales", "accesos_cero_seleccionados",
                         "tecnologia_na_global", "tecnologia_na_seleccionada"]
    reporte = {nombre: int(contadores[nombre]) for nombre in nombres_contadores}
    reporte.update({
        "filas_salida": len(tabla), "claves_duplicadas": 0,
        "alcance_control_duplicados": "llave_detalle_todos_los_bloques_del_archivo",
        "origen_csv": origen, "periodo": {"inicio": inicio, "fin": fin}, "trimestre_referencia": 4,
        "filas_por_anio": {str(anio): int(cantidad) for anio, cantidad in tabla.groupby("anio").size().items()},
        "resumen_anual_accesos": resumen_anual,
        "estados_internet": {str(estado): int(cantidad) for estado, cantidad in tabla["estado_internet"].value_counts().items()},
        "filas_revision_territorial": int(tabla["revision_territorial_pendiente"].sum()),
        "filas_segmento_pendiente": int(tabla["segmento_pendiente_revision"].sum()),
        "filas_metadatos_pendientes": int(tabla["metadatos_reporte_pendientes"].sum()),
        "filas_departamento_inconsistente": int(tabla["departamento_inconsistente"].sum()),
        "filas_accesos_no_utilizables": int(tabla["registros_accesos_no_utilizables"].gt(0).sum()),
        "ejemplos_accesos_invalidos": ejemplos_invalidos, "ejemplos_nacionales": ejemplos_nacionales,
        "faltantes_por_columna": {nombre: int(faltantes[nombre]) for nombre in COLUMNAS},
        "segmentos_observados": [{"id": codigo, "nombre": nombre, "registros": int(cantidad)} for (codigo, nombre), cantidad in sorted(segmentos.items(), key=lambda par: (par[0][0], par[0][1] or ""))],
        "tecnologias_observadas": [{"id": codigo, "nombre": nombre, "registros": int(cantidad)} for (codigo, nombre), cantidad in sorted(tecnologias.items(), key=lambda par: (par[0][0], par[0][1] or ""))],
        "controles_velocidades": {nombre: {"no_utilizables": int(contadores[nombre + "_no_utilizables"]),
                                          "ceros": int(contadores[nombre + "_ceros"])} for nombre in VELOCIDADES},
        "columnas_nuevas_no_agregadas": sorted(columnas_nuevas),
        "velocidad_ponderada_calculada": False, "participacion_fibra_calculada": False,
    })
    LOGGER.info("Internet preparado: %s filas T4 en %s territorios-anio", contadores["filas_seleccionadas"], len(tabla))
    return tabla, reporte
