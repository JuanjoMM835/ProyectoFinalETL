"""Coordinar fuentes, Silver, integracion territorial e indicadores Gold."""

import argparse
import logging
import platform
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import pandas as pd
import pyarrow
import yaml

from src.extract.extract_education import extraer_educacion
from src.extract.extract_population import extraer_poblacion
from src.extract.extract_divipola import extraer_divipola
from src.extract.extract_internet import extraer_internet
from src.extract.read_silver import leer_silver
from src.extract.read_integrated import leer_panel_integrado
from src.transform.clean_education import limpiar_educacion
from src.transform.clean_population import limpiar_poblacion
from src.transform.clean_divipola import limpiar_divipola
from src.transform.clean_internet import limpiar_internet
from src.transform.quality_silver import construir_reporte_silver
from src.transform.integrate_sources import integrar_fuentes
from src.transform.build_indicators import construir_indicadores
from src.transform.resolve_territory import cargar_evidencia_territorial
from src.load.execution_metadata import (
    capturar_entradas, crear_metadata_silver, huella_archivo,
    capturar_codigo, crear_metadata_integracion,
    crear_metadata_indicadores,
)
from src.load.export_results import exportar_silver, _validar_nombre
from src.load.export_integration import exportar_integracion
from src.load.export_gold import exportar_gold


# __file__ permite encontrar el proyecto incluso desde otra carpeta de terminal.
RAIZ_PROYECTO = Path(__file__).resolve().parent


def _cargar_configuracion(
    ruta_configuracion: Optional[Path] = None,
) -> Dict[str, Any]:
    """Compartir la lectura del YAML y del formato de mensajes entre fuentes."""
    ruta = ruta_configuracion or RAIZ_PROYECTO / "config" / "config.yaml"
    # safe_load interpreta datos YAML sin ejecutar objetos de Python.
    with Path(ruta).open("r", encoding="utf-8") as archivo:
        configuracion = yaml.safe_load(archivo)
    if not isinstance(configuracion, dict):
        raise ValueError("La configuracion debe ser un diccionario YAML.")
    # El nivel y formato de los mensajes tambien vienen del YAML acordado.
    opciones_log = configuracion["logging"]
    logging.basicConfig(
        level=opciones_log["level"], format=opciones_log["format"]
    )
    return configuracion


def ejecutar_educacion(
    ruta_configuracion: Optional[Path] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Coordinar lectura y limpieza educativas; devolver tabla y reporte."""
    configuracion = _cargar_configuracion(ruta_configuracion)

    # Como en el ejemplo del curso, main coordina funciones especializadas.
    # La configuracion llega al extractor y al transformador sin rutas personales.
    originales = extraer_educacion(
        configuracion["sources"]["education_stats"], RAIZ_PROYECTO
    )
    return limpiar_educacion(originales, configuracion)


def ejecutar_poblacion(
    ruta_configuracion: Optional[Path] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Preparar DANE de forma independiente, sin cruzar ni escribir resultados."""
    configuracion = _cargar_configuracion(ruta_configuracion)
    originales = extraer_poblacion(
        configuracion["sources"]["population"], RAIZ_PROYECTO
    )
    return limpiar_poblacion(originales, configuracion)


def ejecutar_divipola(
    ruta_configuracion: Optional[Path] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Preparar el catalogo independiente, sin cambiar otras fuentes ni su historia."""
    configuracion = _cargar_configuracion(ruta_configuracion)
    originales = extraer_divipola(
        configuracion["sources"]["divipola"], RAIZ_PROYECTO
    )
    return limpiar_divipola(originales, configuracion)


def ejecutar_internet(
    ruta_configuracion: Optional[Path] = None,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Consumir los bloques del CSV y devolver accesos T4 y controles anuales."""
    configuracion = _cargar_configuracion(ruta_configuracion)
    # closing cierra el generador y su archivo incluso si una validacion falla.
    # El transformador consume los bloques; main no los convierte en una lista.
    with closing(extraer_internet(
        configuracion["sources"]["internet_access"], RAIZ_PROYECTO
    )) as originales:
        return limpiar_internet(originales, configuracion)


def _abrir_log_silver(configuracion: Dict[str, Any]) -> logging.FileHandler:
    """Abrir el historial de ejecuciones en una carpeta segura del proyecto."""
    carpeta = (RAIZ_PROYECTO / configuracion["paths"]["logs_dir"]).resolve()
    if carpeta != RAIZ_PROYECTO and RAIZ_PROYECTO not in carpeta.parents:
        raise ValueError("La carpeta de logs debe quedar dentro del proyecto.")
    for opcion in ("bronze_dir", "silver_dir", "gold_dir"):
        protegida = (RAIZ_PROYECTO / configuracion["paths"][opcion]).resolve()
        if carpeta == protegida or protegida in carpeta.parents:
            raise ValueError("El log debe escribir fuera de las carpetas de datos.")
    nombre = _validar_nombre(configuracion["logging"]["file_name"], ".log", "logging.file_name")
    ruta = (carpeta / nombre).resolve()
    if ruta != RAIZ_PROYECTO and RAIZ_PROYECTO not in ruta.parents:
        raise ValueError("El archivo log debe quedar dentro del proyecto.")
    for opcion in ("bronze_dir", "silver_dir", "gold_dir"):
        protegida = (RAIZ_PROYECTO / configuracion["paths"][opcion]).resolve()
        if ruta == protegida or protegida in ruta.parents:
            raise ValueError("El archivo log debe escribir fuera de las carpetas de datos.")
    for fuente in configuracion["sources"].values():
        if ruta == (RAIZ_PROYECTO / fuente["path"]).resolve():
            raise ValueError("El log no puede sobrescribir una fuente de entrada.")
    carpeta.mkdir(parents=True, exist_ok=True)
    # Append conserva las ejecuciones anteriores; los reportes describen la ultima.
    manejador = logging.FileHandler(ruta, mode="a", encoding="utf-8")
    manejador.setFormatter(logging.Formatter(configuracion["logging"]["format"]))
    logging.getLogger().addHandler(manejador)
    return manejador


def ejecutar_silver(
    ruta_configuracion: Optional[Path] = None,
) -> Dict[str, Any]:
    """Preparar cuatro fuentes, revisar su calidad y guardar tablas y evidencia."""
    ruta = Path(ruta_configuracion or RAIZ_PROYECTO / "config" / "config.yaml").resolve()
    # La huella inicial impide describir otro YAML si se edita durante la run.
    huella_config = huella_archivo(ruta)
    configuracion = _cargar_configuracion(ruta)
    ejecucion_id = str(uuid4())
    inicio = datetime.now(timezone.utc).isoformat()
    log_archivo = _abrir_log_silver(configuracion)
    nivel_anterior = logging.getLogger().level
    # En notebooks puede existir logging previo; habilitar el nivel de esta run.
    logging.getLogger().setLevel(configuracion["logging"]["level"])
    logger = logging.getLogger(__name__)
    try:
        logger.info("Inicio Silver, ejecucion %s.", ejecucion_id)
        entradas = capturar_entradas(configuracion, RAIZ_PROYECTO)
        # Una misma copia de configuracion gobierna las cuatro fuentes de esta run.
        preparadores = {
            "educacion": ("education_stats", extraer_educacion, limpiar_educacion),
            "poblacion": ("population", extraer_poblacion, limpiar_poblacion),
            "divipola": ("divipola", extraer_divipola, limpiar_divipola),
            "internet": ("internet_access", extraer_internet, limpiar_internet),
        }
        tablas, reportes = {}, {}
        for nombre, (clave, extraer, limpiar) in preparadores.items():
            logger.info("Preparando fuente Silver: %s.", nombre)
            originales = extraer(configuracion["sources"][clave], RAIZ_PROYECTO)
            if nombre == "internet":
                # Cerrar el generador tambien ante un error de validacion.
                with closing(originales):
                    tablas[nombre], reportes[nombre] = limpiar(originales, configuracion)
            else:
                tablas[nombre], reportes[nombre] = limpiar(originales, configuracion)
        calidad = construir_reporte_silver(tablas, reportes, configuracion, ejecucion_id)
        metadata = crear_metadata_silver(
            configuracion, RAIZ_PROYECTO, ruta, ejecucion_id, inicio, entradas, huella_config
        )
        metadata["entorno"] = {
            "python": platform.python_version(), "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__, "pyyaml": yaml.__version__,
        }
        # Load recibe datos terminados: guarda y comprueba, sin limpiar de nuevo.
        resultado = exportar_silver(tablas, calidad, metadata, configuracion, RAIZ_PROYECTO)
        logger.info("Ejecucion %s completada: Silver exploratoria, aceptacion del panel no evaluada.", ejecucion_id)
        return resultado
    except Exception:
        # El log registra fallos; una ejecucion fallida no aparenta nuevos reportes exitosos.
        logger.exception("Ejecucion Silver %s fallida; consultar la causa.", ejecucion_id)
        raise
    finally:
        # No duplicar manejadores al ejecutar Silver varias veces desde un notebook.
        logging.getLogger().removeHandler(log_archivo)
        log_archivo.close()
        logging.getLogger().setLevel(nivel_anterior)


def ejecutar_integracion(
    ruta_configuracion: Optional[Path] = None,
) -> Dict[str, Any]:
    """Leer Silver, cruzar el universo MEN y guardar un panel con diagnosticos."""
    ruta = Path(ruta_configuracion or RAIZ_PROYECTO / "config" / "config.yaml").resolve()
    huella_config = huella_archivo(ruta)
    configuracion = _cargar_configuracion(ruta)
    codigo = capturar_codigo(configuracion, RAIZ_PROYECTO)
    ejecucion_id, inicio = str(uuid4()), datetime.now(timezone.utc).isoformat()
    # Reutilizamos el manejo del log, con un nombre propio para esta etapa.
    config_log = deepcopy(configuracion)
    config_log["logging"]["file_name"] = configuracion["logging"]["integration_file_name"]
    log_archivo = _abrir_log_silver(config_log)
    nivel_anterior = logging.getLogger().level
    logging.getLogger().setLevel(configuracion["logging"]["level"])
    logger = logging.getLogger(__name__)
    try:
        logger.info("Inicio integracion, ejecucion %s.", ejecucion_id)
        # El extractor nuevo consume las salidas ya limpias, no los originales.
        tablas, procedencia = leer_silver(configuracion, RAIZ_PROYECTO)
        evidencia = deepcopy(procedencia["catalogo_temporal"])
        referencias = cargar_evidencia_territorial(configuracion, RAIZ_PROYECTO)
        evidencia.update(referencias)
        procedencia["entradas_referencia"] = referencias.get("entradas_referencia", [])
        panel, reporte = integrar_fuentes(tablas, configuracion, evidencia)
        reporte["ejecucion_id"] = ejecucion_id
        reporte["version_contrato"] = configuracion["project"]["data_contract"]["version"]
        reporte["periodo"] = {"inicio": configuracion["processing"]["year_start"],
                              "fin": configuracion["processing"]["year_end"]}
        metadata = crear_metadata_integracion(
            configuracion, RAIZ_PROYECTO, ruta, ejecucion_id, inicio,
            procedencia, huella_config, codigo,
        )
        metadata["entorno"] = {
            "python": platform.python_version(), "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__, "pyyaml": yaml.__version__,
        }
        # El resumen facilita la consola; el reporte conserva el detalle completo.
        metadata["resumen_integracion"] = {
            "filas_panel": len(panel), "diagnosticos": reporte["diagnosticos"],
            "homologacion": reporte["homologacion"],
            "conjunto_critico": reporte["conjunto_critico"],
            "aceptacion_panel": reporte["aceptacion_panel"],
        }
        resultado = exportar_integracion(panel, reporte, metadata, configuracion, RAIZ_PROYECTO)
        logger.info("Integracion completada: %s filas, aceptacion %s, estado exploratorio.",
                    len(panel), reporte["aceptacion_panel"]["estado"])
        return resultado
    except Exception:
        logger.exception("Integracion %s fallida; consultar la causa.", ejecucion_id)
        raise
    finally:
        # Evitar manejadores duplicados al llamar esta funcion desde un notebook.
        logging.getLogger().removeHandler(log_archivo)
        log_archivo.close()
        logging.getLogger().setLevel(nivel_anterior)


def ejecutar_gold(
    ruta_configuracion: Optional[Path] = None,
) -> Dict[str, Any]:
    """Calcular seis indicadores e índice de prioridad en la Gold exploratoria."""
    ruta = Path(ruta_configuracion or RAIZ_PROYECTO / "config" / "config.yaml").resolve()
    huella_config = huella_archivo(ruta)
    configuracion = _cargar_configuracion(ruta)
    codigo = capturar_codigo(configuracion, RAIZ_PROYECTO)
    ejecucion_id, inicio = str(uuid4()), datetime.now(timezone.utc).isoformat()
    config_log = deepcopy(configuracion)
    config_log["logging"]["file_name"] = configuracion["logging"]["gold_file_name"]
    log_archivo = _abrir_log_silver(config_log)
    nivel_anterior = logging.getLogger().level
    logging.getLogger().setLevel(configuracion["logging"]["level"])
    logger = logging.getLogger(__name__)
    try:
        logger.info("Inicio indicadores, ejecucion %s.", ejecucion_id)
        panel, procedencia = leer_panel_integrado(configuracion, RAIZ_PROYECTO)
        datos, reporte = construir_indicadores(panel, configuracion)
        reporte["ejecucion_id"] = ejecucion_id
        reporte["version_contrato"] = configuracion["project"]["data_contract"]["version"]
        reporte["aceptacion_panel"] = deepcopy(procedencia["aceptacion_panel"])
        reporte["periodo"] = {"inicio": configuracion["processing"]["year_start"],
                              "fin": configuracion["processing"]["year_end"]}
        # Crear archivos Gold no cambia la aceptacion de los datos que los originan.
        metadata = crear_metadata_indicadores(
            configuracion, RAIZ_PROYECTO, ruta, ejecucion_id, inicio,
            procedencia, huella_config, codigo,
        )
        metadata["entorno"] = {
            "python": platform.python_version(), "pandas": pd.__version__,
            "pyarrow": pyarrow.__version__, "pyyaml": yaml.__version__,
        }
        metadata["resumen_indicadores"] = {
            "filas_panel": len(datos), "indicadores": reporte["indicadores"],
            "aceptacion_panel": reporte["aceptacion_panel"],
        }
        resultado = exportar_gold(datos, reporte, metadata, configuracion, RAIZ_PROYECTO)
        logger.info("Indicadores guardados: %s filas, estado exploratorio, aceptacion %s.",
                    len(datos), reporte["aceptacion_panel"]["estado"])
        return resultado
    except Exception:
        logger.exception("Indicadores %s fallidos; consultar la causa.", ejecucion_id)
        raise
    finally:
        logging.getLogger().removeHandler(log_archivo)
        log_archivo.close()
        logging.getLogger().setLevel(nivel_anterior)


def _mostrar_educacion(datos: pd.DataFrame, reporte: Dict[str, Any]) -> None:
    """Mostrar los mismos controles educativos de la etapa anterior."""
    # Presentamos controles que permiten conciliar esta etapa con el notebook.
    print("\nPreparacion educativa completada")
    print("Filas de entrada:", reporte["filas_entrada"])
    print("Registros nacionales separados:", reporte["registros_nacionales_separados"])
    print("Territoriales fuera del periodo:", reporte["registros_territoriales_fuera_periodo"])
    print("Filas de salida:", reporte["filas_salida"])
    print("Llaves duplicadas:", reporte["claves_duplicadas"])
    print("Poblaciones escolares con miles corregidos:", reporte["poblacion_5_16_miles_corregidos"])
    print("Correcciones por separador:", reporte["poblacion_5_16_miles_por_separador"])
    print("Poblaciones escolares no utilizables:", reporte["poblaciones_escolares_no_utilizables"])
    for nombre, estados in reporte["estados_indicadores"].items():
        print("Estado de {}: {}".format(nombre, estados))
    print("Presencia numerica conjunta (solo educacion): {:.2f}%".format(
        reporte["conjunto_educativo"]["porcentaje_presencia_numerica"]
    ))
    print("Utilizables conjuntamente (solo educacion): {:.2f}%".format(
        reporte["conjunto_educativo"]["porcentaje_utilizables"]
    ))
    print("\nMuestra de la tabla limpia:")
    print(datos[["codigo_municipio", "anio", "municipio", "cobertura_neta", "desercion"]]
          .head().to_string(index=False))


def _mostrar_poblacion(datos: pd.DataFrame, reporte: Dict[str, Any]) -> None:
    """Mostrar origen, pivote y controles del conjunto poblacional."""
    print("\nPreparacion de poblacion completada")
    print("Filas de la hoja leidas:", reporte["filas_entrada"])
    print("Filas vacias separadas:", reporte["filas_vacias"])
    print("Notas de la fuente conservadas:", len(reporte["notas_archivo"]))
    print("Filas tabulares:", reporte["filas_datos"])
    print("Filas tabulares fuera del periodo:", reporte["filas_fuera_periodo"])
    print("Filas por area seleccionadas:", reporte["filas_seleccionadas"])
    print("Territorios-anio de salida:", reporte["filas_salida"])
    print("Llaves duplicadas:", reporte["claves_duplicadas"])
    print("Areas incompletas:", reporte["areas_incompletas"])
    print("Componentes inconsistentes:", reporte["componentes_inconsistentes"])
    print("Poblaciones en cero:", reporte["poblaciones_en_cero"])
    print("Estados poblacionales:", reporte["estados_poblacion"])
    print("Denominadores positivos:", reporte["denominadores_positivos"])
    print("Poblaciones utilizables para ratios:", reporte["poblaciones_para_ratios_utilizables"])
    print("\nMuestra de la tabla anual:")
    print(datos[["codigo_municipio", "anio", "municipio", "poblacion_total",
                 "poblacion_cabecera", "poblacion_centros_rural"]].head().to_string(index=False))


def _mostrar_divipola(datos: pd.DataFrame, reporte: Dict[str, Any]) -> None:
    """Mostrar la calidad del catalogo sin presentarla como homologacion anual."""
    print("\nPreparacion de DIVIPOLA completada")
    print("Territorios leidos:", reporte["filas_entrada"])
    print("Territorios de salida:", reporte["filas_salida"])
    print("Codigos departamentales:", reporte["departamentos_distintos"])
    print("Claves duplicadas:", reporte["claves_duplicadas"])
    print("Departamentos inconsistentes:", reporte["departamentos_inconsistentes"])
    print("Metadatos incompletos:", reporte["metadatos_incompletos"])
    print("Tipos territoriales:", reporte["tipos_territorio"])
    print("Estados del catalogo:", reporte["estados_catalogo"])
    print("Pares de coordenadas utilizables:", reporte["filas_con_coordenadas_utilizables"])
    print("Vigencia historica verificada:", reporte["vigencia_historica_verificada"])
    print("\nMuestra del catalogo limpio:")
    print(datos[["codigo_municipio", "municipio", "codigo_departamento",
                 "departamento", "tipo_territorio"]].head().to_string(index=False))


def _mostrar_internet(datos: pd.DataFrame, reporte: Dict[str, Any]) -> None:
    """Separar presencia numerica y revisiones semanticas en el resumen de T4."""
    print("\nPreparacion de internet fijo completada")
    print("Bloques leidos:", reporte["bloques_leidos"])
    print("Filas originales revisadas:", reporte["filas_entrada"])
    print("Filas fuera del periodo:", reporte["filas_fuera_periodo"])
    print("Otros trimestres dentro del periodo:", reporte["filas_otros_trimestres_periodo"])
    print("Nacionales T4 separados:", reporte["filas_nacionales_t4_separados"])
    print("Filas territoriales T4 seleccionadas:", reporte["filas_seleccionadas"])
    print("Territorios-anio de salida:", reporte["filas_salida"])
    print("Llaves de reporte duplicadas:", reporte["claves_duplicadas"])
    print("Estados de internet:", reporte["estados_internet"])
    print("Filas con revision territorial:", reporte["filas_revision_territorial"])
    print("Filas con segmentos pendientes:", reporte["filas_segmento_pendiente"])
    print("Filas con accesos no utilizables:", reporte["filas_accesos_no_utilizables"])
    # Son sumas observadas para conciliar la fuente; un estado pendiente sigue
    # pendiente aunque exista una cifra numerica en esta tabla de diagnostico.
    print("\nSumas observadas por anio (incluyen los casos pendientes):")
    print(pd.DataFrame(reporte["resumen_anual_accesos"]).to_string(index=False))
    print("\nMuestra de la tabla anual:")
    print(datos[["codigo_municipio", "anio", "municipio", "accesos_t4",
                 "estado_internet"]].head().to_string(index=False))


def _mostrar_silver(metadata: Dict[str, Any]) -> None:
    """Presentar los archivos persistidos y el alcance de sus controles."""
    print("\nCapa Silver guardada y verificada")
    print("Ejecucion:", metadata["ejecucion_id"])
    for fuente, salida in metadata["salidas"].items():
        print("{}: {} filas -> {}".format(fuente, salida["filas"], salida["archivo"]))
    print("Reporte de calidad:", metadata["reporte_calidad"]["archivo"])
    print("Metadata:", metadata["metadata_ejecucion"]["archivo"])
    print("Estado: exploratorio. La aceptacion del panel integrado todavia no se evalua.")


def _mostrar_integracion(metadata: Dict[str, Any]) -> None:
    """Explicar coincidencias, calidad y alcance del panel intermedio guardado."""
    resumen = metadata["resumen_integracion"]
    print("\nPanel integrado exploratorio guardado y verificado")
    print("Ejecucion:", metadata["ejecucion_id"])
    print("Filas MEN conservadas:", resumen["filas_panel"])
    for fuente in ("poblacion", "internet", "divipola"):
        diagnostico = resumen["diagnosticos"][fuente]
        print("{}: {} coincidencias; {} filas MEN sin coincidencia.".format(
            fuente, diagnostico["coincidencias"], diagnostico["sin_coincidencia"]))
    print("Homologacion temporal acreditada: {:.2f}%".format(resumen["homologacion"]["porcentaje"]))
    print("Seis variables utilizables segun las fuentes: {:.2f}%".format(
        resumen["conjunto_critico"]["porcentaje_utilizables_fuente"]))
    print("Aceptacion del panel:", resumen["aceptacion_panel"]["estado"])
    print("Panel:", metadata["salidas"]["panel_integrado"]["archivo"])
    print("Reporte:", metadata["reporte_integracion"]["archivo"])
    print("Metadata:", metadata["metadata_integracion"]["archivo"])
    print("La identidad se acredita por codigo y anio exactos. Para calcular indicadores: --gold.")


def _mostrar_gold(metadata: Dict[str, Any]) -> None:
    """Distinguir resultados acreditados y diagnosticos locales en la consola."""
    resumen = metadata["resumen_indicadores"]
    print("\nIndicadores Gold exploratorios guardados y verificados")
    print("Filas MEN conservadas:", resumen["filas_panel"])
    for nombre, controles in resumen["indicadores"].items():
        print("{}: {} calculables con identidad acreditada; {} candidatos de diagnostico.".format(
            nombre, controles["numerador_calculables"], controles["numerador_diagnostico"]))
    print("Aceptacion del panel:", resumen["aceptacion_panel"]["estado"])
    for nombre, salida in metadata["salidas"].items():
        print("{}: {}".format(nombre, salida["archivo"]))
    print("Reporte:", metadata["reporte_indicadores"]["archivo"])
    print("Metadata:", metadata["metadata_indicadores"]["archivo"])
    print("Los campos _diagnostico no acreditan identidad territorial ni Gold validada.")


def main() -> None:
    """Elegir fuente, Silver, integracion o calculo de indicadores Gold."""
    parser = argparse.ArgumentParser(description="Preparar fuentes, Silver, panel MEN o indicadores Gold.")
    modo = parser.add_mutually_exclusive_group()
    # Conservamos educacion como opcion predeterminada del comando anterior.
    modo.add_argument("--fuente", choices=["educacion", "poblacion", "divipola", "internet"], default="educacion",
                        help="Fuente que se preparara; por defecto, educacion.")
    modo.add_argument("--silver", action="store_true", help="Guardar las cuatro tablas Silver y sus reportes.")
    modo.add_argument("--integrar", action="store_true", help="Integrar los cuatro Silver sin releer Bronze.")
    modo.add_argument("--gold", action="store_true", help="Calcular indicadores desde el panel integrado y guardar Parquet/CSV.")
    parser.add_argument("--config", type=Path, help="Ruta opcional a otro archivo YAML.")
    argumentos = parser.parse_args()
    try:
        if argumentos.gold:
            _mostrar_gold(ejecutar_gold(argumentos.config))
            return
        if argumentos.integrar:
            _mostrar_integracion(ejecutar_integracion(argumentos.config))
            return
        if argumentos.silver:
            _mostrar_silver(ejecutar_silver(argumentos.config))
            return
        if argumentos.fuente == "internet":
            datos, reporte = ejecutar_internet(argumentos.config)
            _mostrar_internet(datos, reporte)
        elif argumentos.fuente == "divipola":
            datos, reporte = ejecutar_divipola(argumentos.config)
            _mostrar_divipola(datos, reporte)
        elif argumentos.fuente == "poblacion":
            datos, reporte = ejecutar_poblacion(argumentos.config)
            _mostrar_poblacion(datos, reporte)
        else:
            datos, reporte = ejecutar_educacion(argumentos.config)
            _mostrar_educacion(datos, reporte)
    except (OSError, ValueError, KeyError, TypeError, AssertionError, RuntimeError, yaml.YAMLError) as error:
        # Una entrada invalida debe producir salida de error, no aparentar exito.
        etapa = "indicadores" if argumentos.gold else "integracion" if argumentos.integrar else "silver" if argumentos.silver else argumentos.fuente
        logging.error("No se pudo preparar %s: %s", etapa, error)
        raise SystemExit(1) from error
    # Los comandos de una sola fuente siguen devolviendo resultados en memoria.
    print("\nResultado en memoria: esta etapa no genera archivos Silver ni Gold.")


# Importar este modulo desde un notebook no ejecuta automaticamente el proceso.
if __name__ == "__main__":
    main()
