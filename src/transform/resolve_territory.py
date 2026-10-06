"""Acreditar identidad territorial solo con catálogos DANE del año observado.

No se interpolan años ni se remapean códigos históricos. Los JSON originales
se conservan y sus huellas vinculan cada decisión con una referencia concreta.
"""

from copy import deepcopy
import logging
import math
from pathlib import Path
import re
from typing import Any, Dict, Mapping
import unicodedata
from urllib.parse import urlparse

import pandas as pd

from src.extract.read_silver import _leer_json
from src.load.execution_metadata import huella_archivo


LOGGER = logging.getLogger(__name__)
CRITERIOS = {"capa_anual", "anio_registro"}


def _codigo(valor: Any, longitud: int) -> bool:
    """Exigir texto completo: nunca completar un código incompleto por suposición."""
    return (isinstance(valor, str) and bool(re.fullmatch(r"[0-9]{%s}" % longitud, valor))
            and valor != "0" * longitud)


def _texto(valor: Any):
    """Conservar nombres documentados; un nombre ausente permanece desconocido."""
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def _tipo(valor: Any):
    """Normalizar categorías explícitas sin usar el catálogo actual para el pasado."""
    texto = _texto(valor)
    if texto is None:
        return None
    texto = "".join(caracter for caracter in unicodedata.normalize("NFKD", texto)
                    if not unicodedata.combining(caracter))
    clave = "_".join(texto.upper().split())
    return {"MUNICIPIO": "municipio", "AREA_NO_MUNICIPALIZADA": "area_no_municipalizada",
            "ANM": "area_no_municipalizada", "ISLA": "isla"}.get(clave)


def _anio(valor: Any):
    """Aceptar años enteros documentados y rechazar booleanos o fracciones."""
    if hasattr(valor, "item"):
        valor = valor.item()
    if type(valor) is int:
        return valor
    if isinstance(valor, str) and re.fullmatch(r"[0-9]{4}", valor.strip()):
        return int(valor.strip())
    if isinstance(valor, float) and math.isfinite(valor) and valor.is_integer():
        return int(valor)
    return None


def _validar_catalogo(catalogo: Mapping) -> None:
    """Comprobar año, criterio explícito y referencia oficial DANE."""
    if not isinstance(catalogo, Mapping) or type(catalogo.get("anio")) is not int:
        raise ValueError("Cada catálogo territorial debe declarar un año entero.")
    if not 2018 <= catalogo["anio"] <= 2024 or catalogo.get("criterio_temporal") not in CRITERIOS:
        raise ValueError("El catálogo requiere año 2018–2024 y un criterio temporal reconocido.")
    referencia = catalogo.get("referencia")
    if not isinstance(referencia, str):
        raise ValueError("Falta la referencia oficial del catálogo territorial.")
    url = urlparse(referencia)
    if url.scheme != "https" or not url.hostname or not (
        url.hostname == "dane.gov.co" or url.hostname.endswith(".dane.gov.co")
    ):
        raise ValueError("La evidencia territorial debe citar una referencia HTTPS oficial DANE.")


def _ruta_referencia(valor: Any, raiz: Path, carpeta: Path) -> Path:
    """Limitar las entradas locales a JSON de data/reference dentro del proyecto."""
    if not isinstance(valor, str) or not valor:
        raise ValueError("Falta la ruta de una referencia territorial.")
    relativa = Path(valor)
    base = carpeta if not relativa.is_absolute() and len(relativa.parts) == 1 else raiz
    ruta = (base / relativa).resolve()
    if raiz not in ruta.parents or carpeta not in ruta.parents or ruta.suffix.lower() != ".json":
        raise ValueError(f"La referencia debe permanecer en data/reference: {ruta}")
    if not ruta.is_file():
        raise FileNotFoundError(f"No existe la referencia territorial: {ruta}")
    return ruta


def _entrada_verificada(registro: Mapping, raiz: Path, carpeta: Path) -> Dict[str, Any]:
    """Verificar bytes y huella de un snapshot o su metadata antes de leerlo."""
    if not isinstance(registro, Mapping):
        raise ValueError("La referencia debe tener archivo, tamaño y SHA-256.")
    ruta = _ruta_referencia(registro.get("archivo"), raiz, carpeta)
    tamano, huella = registro.get("tamano_bytes"), registro.get("sha256")
    if (type(tamano) is not int or tamano < 0 or not isinstance(huella, str)
            or not re.fullmatch(r"[0-9a-f]{64}", huella)):
        raise ValueError("El tamaño o SHA-256 de la referencia territorial no es válido.")
    if ruta.stat().st_size != tamano or huella_archivo(ruta) != huella:
        raise ValueError(f"La referencia territorial no coincide con su manifiesto: {ruta.name}")
    return {"archivo": str(ruta), "sha256": huella, "tamano_bytes": tamano}


def _fila_normalizada(valores: Mapping) -> Dict[str, Any]:
    """Aceptar identidad completa y consistente; un registro inválido no acredita nada."""
    if not isinstance(valores, Mapping):
        return None
    codigo, departamento = valores.get("codigo_municipio"), valores.get("codigo_departamento")
    nombre = _texto(valores.get("municipio"))
    if (not _codigo(codigo, 5) or not _codigo(departamento, 2)
            or codigo[:2] != departamento or nombre is None):
        return None
    return {"codigo_municipio": codigo, "codigo_departamento": departamento,
            "municipio": nombre, "departamento": _texto(valores.get("departamento")),
            "tipo_territorio": _tipo(valores.get("tipo_territorio"))}


def _identidad(registro: Mapping, quitar_marca_anm: bool = False) -> tuple:
    """Comparar duplicados con espacios/case normalizados, sin similitud aproximada."""
    nombre = registro["municipio"]
    if quitar_marca_anm:
        # Las capas 2018 añaden (ANM) a PACOA/PAPUNAUA/YAVARATÉ en la capa general.
        # Solo se retira este marcador al comparar con la capa específica ANM;
        # los JSON y nombres de ambos snapshots permanecen intactos.
        nombre = re.sub(r"\s*\(ANM\)\s*$", "", nombre, flags=re.IGNORECASE)
    return (registro["codigo_departamento"],
            " ".join(nombre.split()).casefold())


def _indexar_catalogos(catalogos: list) -> dict:
    """Construir una sola evidencia por código-año y resolver el solapamiento 2018.

    La capa 1 de 2018 contiene también las ANM de la capa 2. Sus identidades
    deben coincidir; solo la capa explícita ANM acredita esa categoría. Un
    conflicto de código/departamento/nombre detiene la aplicación de evidencias.
    """
    indice = {}
    if not isinstance(catalogos, list):
        raise ValueError("catalogos_anuales debe ser una lista.")
    for catalogo in catalogos:
        _validar_catalogo(catalogo)
        registros = catalogo.get("registros")
        if not isinstance(registros, list):
            raise ValueError("Cada catálogo cargado debe contener una lista de registros.")
        for original in registros:
            registro = _fila_normalizada(original)
            if registro is None:
                continue
            registro.update(anio=catalogo["anio"], referencia=catalogo["referencia"],
                            criterio_temporal=catalogo["criterio_temporal"])
            llave = (registro["codigo_municipio"], registro["anio"])
            if llave not in indice:
                indice[llave] = registro
                continue
            anterior = indice[llave]
            solapamiento = (registro["anio"] == 2018
                            and anterior["criterio_temporal"] == registro["criterio_temporal"] == "capa_anual"
                            and anterior["referencia"] != registro["referencia"])
            identica = _identidad(anterior) == _identidad(registro)
            if (not identica and solapamiento
                    and anterior["codigo_departamento"] == registro["codigo_departamento"]
                    and "area_no_municipalizada" in {anterior["tipo_territorio"], registro["tipo_territorio"]}):
                identica = _identidad(anterior, True) == _identidad(registro, True)
            if not solapamiento or not identica:
                raise ValueError(f"Código-año territorial duplicado o conflictivo: {llave}")
            nombres_departamento = [_texto(fila["departamento"]) for fila in (anterior, registro)]
            if all(nombres_departamento) and nombres_departamento[0].casefold() != nombres_departamento[1].casefold():
                raise ValueError(f"Nombres departamentales conflictivos en la evidencia: {llave}")
            tipos = {fila["tipo_territorio"] for fila in (anterior, registro)} - {None}
            if len(tipos) > 1 and "area_no_municipalizada" not in tipos:
                raise ValueError(f"Categorías territoriales conflictivas en la evidencia: {llave}")
            if registro["tipo_territorio"] == "area_no_municipalizada":
                indice[llave] = registro
            elif anterior["tipo_territorio"] is None and registro["tipo_territorio"] is not None:
                indice[llave] = registro
    return indice


def cargar_evidencia_territorial(configuracion: Mapping, raiz_proyecto: Path) -> Dict[str, Any]:
    """Cargar snapshots verificados y limitar cada uno al año que documenta.

    Omitir la opción o deshabilitarla mantiene el comportamiento conservador de
    las pruebas anteriores. Los años mixtos se filtran por el atributo declarado,
    nunca por la fecha del archivo, el nombre del servicio o un año vecino.
    """
    opciones = configuracion.get("territorial_evidence", {})
    if not isinstance(opciones, Mapping) or type(opciones.get("enabled", False)) is not bool:
        raise ValueError("territorial_evidence.enabled debe ser booleano.")
    if not opciones.get("enabled", False):
        return {}
    raiz = Path(raiz_proyecto).resolve(strict=True)
    carpeta = (raiz / "data/reference").resolve()
    if raiz not in carpeta.parents:
        raise ValueError("data/reference debe quedar dentro del proyecto.")
    ruta_manifest = _ruta_referencia(opciones.get("manifest"), raiz, carpeta)
    huella_manifest = huella_archivo(ruta_manifest)
    manifiesto = _leer_json(ruta_manifest)
    catalogos = manifiesto.get("catalogos_anuales")
    if not isinstance(catalogos, list) or not catalogos:
        raise ValueError("El manifiesto debe declarar catálogos anuales de referencia.")
    entradas = [{"archivo": str(ruta_manifest), "sha256": huella_manifest,
                 "tamano_bytes": int(ruta_manifest.stat().st_size)}]
    cargados = []
    for catalogo in catalogos:
        _validar_catalogo(catalogo)
        entrada = _entrada_verificada(catalogo, raiz, carpeta)
        entradas.append(entrada)
        if "metadata" in catalogo:
            entradas.append(_entrada_verificada(catalogo["metadata"], raiz, carpeta))
        documento = _leer_json(Path(entrada["archivo"]))
        features = documento.get("features")
        columnas = catalogo.get("columnas")
        if (not isinstance(features, list) or not isinstance(columnas, Mapping)
                or any(not isinstance(columnas.get(nombre), str) or not columnas[nombre]
                       for nombre in ("codigo", "departamento", "nombre"))):
            raise ValueError("El snapshot requiere features y columnas de código, departamento y nombre.")
        if "numero_registros" in catalogo and catalogo["numero_registros"] != len(features):
            raise ValueError("La cantidad del snapshot no coincide con el manifiesto.")
        campo_anio = columnas.get("anio_registro")
        if catalogo["criterio_temporal"] == "anio_registro" and not isinstance(campo_anio, str):
            raise ValueError("El criterio anio_registro requiere su columna explícita.")
        registros, fuera_anio, invalidas = [], 0, 0
        for feature in features:
            atributos = feature.get("attributes") if isinstance(feature, Mapping) else None
            if not isinstance(atributos, Mapping):
                invalidas += 1
                continue
            if catalogo["criterio_temporal"] == "anio_registro":
                anio_registro = _anio(atributos.get(campo_anio))
                if anio_registro != catalogo["anio"]:
                    fuera_anio += 1
                    continue
            registro = _fila_normalizada({
                "codigo_municipio": atributos.get(columnas["codigo"]),
                "codigo_departamento": atributos.get(columnas["departamento"]),
                "municipio": atributos.get(columnas["nombre"]),
                "departamento": atributos.get(columnas.get("nombre_departamento")),
                "tipo_territorio": atributos.get(columnas["tipo"]) if "tipo" in columnas else catalogo.get("tipo_por_capa"),
            })
            if registro is None:
                invalidas += 1
            else:
                registros.append(registro)
        cargados.append({"anio": catalogo["anio"], "referencia": catalogo["referencia"],
                         "criterio_temporal": catalogo["criterio_temporal"], "registros": registros,
                         "filas_origen": len(features), "filas_fuera_anio": fuera_anio,
                         "filas_invalidas": invalidas})
    _indexar_catalogos(cargados)  # Detectar conflictos antes de modificar cualquier panel.
    for entrada in entradas:
        if huella_archivo(Path(entrada["archivo"])) != entrada["sha256"]:
            raise ValueError("Una referencia territorial cambió durante su lectura.")
    historicos = set()
    for clave in ("population", "internet_access"):
        historicos.update(configuracion.get("sources", {}).get(clave, {}).get("territorial_review_codes", []))
    if any(not _codigo(codigo, 5) for codigo in historicos):
        raise ValueError("Los códigos históricos de revisión deben tener cinco cifras como texto.")
    LOGGER.info("Evidencia cargada: %s snapshots anuales; sin interpolación temporal.", len(cargados))
    return {"vigencia_historica_verificada": False, "catalogos_anuales": cargados,
            "entradas_referencia": entradas, "codigos_revision_territorial": sorted(historicos),
            "manifest": str(ruta_manifest)}


def _booleano(valor: Any):
    """Distinguir False de un control desconocido o de una cadena textual."""
    if hasattr(valor, "item"):
        valor = valor.item()
    return valor if isinstance(valor, bool) else None


def _fila_bloqueada(fila: pd.Series, registro: Mapping, historicos: set) -> bool:
    """Exigir compatibilidad departamental y conservar toda revisión histórica."""
    if fila["codigo_municipio"] in historicos or _booleano(fila["revision_territorial_pendiente"]) is not False:
        return True
    if not _codigo(fila["codigo_departamento"], 2) or fila["codigo_departamento"] != registro["codigo_departamento"]:
        return True
    for bandera in ("departamento_inconsistente_entre_fuentes", "departamento_desconocido_en_coincidencias"):
        if bandera in fila and _booleano(fila[bandera]) is not False:
            return True
    fuentes = [("educacion", True)]
    for fuente in ("poblacion", "internet"):
        coincide = _booleano(fila.get("coincidencia_" + fuente))
        if coincide is None:
            return True
        fuentes.append((fuente, coincide))
        if coincide:
            codigo_fuente = fila.get(fuente + "__codigo_departamento")
            if not _codigo(codigo_fuente, 2) or codigo_fuente != registro["codigo_departamento"]:
                return True
    # La ausencia del catálogo actual no invalida una fila anual documentada.
    coincide_actual = _booleano(fila.get("coincidencia_catalogo_actual"))
    if coincide_actual is True:
        fuentes.append(("divipola", True))
        if _texto(fila.get("estado_catalogo_actual")) != "disponible":
            return True
    for fuente, coincide in fuentes:
        if not coincide:
            continue
        for columna in fila.index:
            if columna.startswith(fuente + "__") and columna.split("__", 1)[1] in {
                "metadatos_incompletos", "metadatos_reporte_pendientes", "departamento_inconsistente",
                "revision_territorial_pendiente",
            } and _booleano(fila[columna]) is not False:
                return True
    return False


def aplicar_evidencia_territorial(panel: pd.DataFrame, evidencia: Mapping) -> pd.DataFrame:
    """Resolver únicamente coincidencias código-año acreditadas y compatibles.

    Los seis valores críticos y los originales prefijados se conservan. Una
    bandera global nunca acredita identidad; cada resolución registra la URL y
    una vigencia de un solo año, sin trasladar datos entre territorios.
    """
    if not isinstance(panel, pd.DataFrame):
        raise TypeError("El panel territorial debe ser un DataFrame.")
    resultado = panel.copy(deep=True)
    resultado.attrs = deepcopy(panel.attrs)
    if not evidencia:
        return resultado
    if not isinstance(evidencia, Mapping) or evidencia.get("vigencia_historica_verificada") or evidencia.get("reglas_verificadas"):
        raise ValueError("Una bandera global no autoriza homologación territorial.")
    indice = _indexar_catalogos(evidencia.get("catalogos_anuales", []))
    if not indice:
        return resultado
    necesarias = {"codigo_municipio", "anio", "codigo_departamento", "municipio", "departamento",
                  "estado_homologacion", "revision_territorial_pendiente"}
    if not necesarias.issubset(resultado.columns):
        raise ValueError("El panel no contiene los campos de identidad y revisión territorial.")
    historicos = set(evidencia.get("codigos_revision_territorial", []))
    resueltas = 0
    for posicion, (_, fila) in enumerate(resultado.iterrows()):
        if _texto(fila["estado_homologacion"]) != "pendiente_revision":
            continue
        registro = indice.get((fila["codigo_municipio"], _anio(fila["anio"])))
        if registro is None or _fila_bloqueada(fila, registro, historicos):
            continue
        valores = {"municipio": registro["municipio"],
                   "fuente_nombre_territorial": "catalogo_dane_anual",
                   "tipo_territorio": registro["tipo_territorio"] or "no_resuelto",
                   "estado_homologacion": "resuelto_catalogo",
                   "motivo_homologacion": "coincidencia_catalogo_anual",
                   "evidencia_homologacion": registro["referencia"],
                   "vigencia_desde": registro["anio"], "vigencia_hasta": registro["anio"]}
        if registro["departamento"] is not None:
            valores["departamento"] = registro["departamento"]
        for columna, valor in valores.items():
            if columna not in resultado:
                tipo = "Int64" if columna in {"vigencia_desde", "vigencia_hasta"} else "string"
                resultado[columna] = pd.Series(pd.NA, index=resultado.index, dtype=tipo)
            # Escribir por posición evita afectar otra fila con el mismo índice técnico.
            resultado.iat[posicion, resultado.columns.get_loc(columna)] = valor
        resueltas += 1
    LOGGER.info("Identidades acreditadas por código-año: %s; revisiones históricas conservadas.", resueltas)
    return resultado
