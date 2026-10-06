# Persistencia de Silver y reportes de calidad

Fecha: 2026-10-06. Esta etapa implementa el punto 4 del orden acordado: guardar las cuatro fuentes preparadas y sus evidencias. El contrato sigue en la versión 1.0; las reglas de limpieza no cambian.

## 1. Qué cambia al guardar Silver

Hasta ahora, cada extractor y transformador devolvía una tabla y un reporte en memoria. Al finalizar Python, esas variables desaparecían. Ahora `main.py --silver` prepara las cuatro fuentes, revisa su estructura y guarda resultados reutilizables.

```text
Bronze original -> extracción -> limpieza -> controles Silver -> Load
                                                                |
                                   cuatro Parquet + calidad + metadata
```

Silver conserva cada fuente de forma independiente. No se unen aún las cuatro tablas ni se calculan indicadores Gold. Los pendientes territoriales, educativos y de segmentos permanecen visibles en sus columnas y reportes.

## 2. Archivos que produce

Las rutas siguientes son relativas a la raíz de `ProyectoFinalETL`:

| Archivo | Contenido y llave |
|---|---|
| `data/silver/educacion_limpia.parquet` | Educación MEN preparada; `codigo_municipio + anio`. |
| `data/silver/poblacion_limpia.parquet` | Población DANE total y por área; `codigo_municipio + anio`. |
| `data/silver/internet_municipio_anio.parquet` | Sumas observadas de T4 y sus estados; `codigo_municipio + anio`. |
| `data/silver/divipola_limpia.parquet` | Catálogo territorial disponible; `codigo_municipio`, sin inventar años. |
| `logs/reporte_calidad.json` | Controles de las cuatro tablas y reportes detallados de extracción y transformación. |
| `logs/metadata_ejecucion.json` | Identificación de la ejecución, fuentes, configuración, código, versiones y archivos publicados. |
| `logs/etl_pipeline.log` | Historial de avance y de errores de las ejecuciones Silver. |

Los Parquet son el formato principal: conservan códigos como texto, ceros iniciales, enteros/decimales anulables y banderas booleanas. Un faltante permanece faltante. No contienen el índice incidental de pandas porque las llaves ya están en columnas.

Los JSON son archivos de texto estructurado, legibles con UTF-8. Los faltantes documentados se expresan como `null`; se rechazan `NaN` e infinitos, y no se convierten objetos erróneos automáticamente a texto.

## 3. Responsabilidad de cada módulo

### `main.py`

`ejecutar_silver(ruta_configuracion=None)`:

1. Lee una configuración compartida y captura su huella inicial.
2. Asigna un identificador único y una fecha inicial UTC a la ejecución.
3. Abre el log en modo acumulativo y calcula huellas de las cuatro entradas.
4. Llama a los extractores y transformadores ya implementados. Internet mantiene lectura por bloques y cierre del generador incluso ante errores.
5. Construye el reporte de calidad de las tablas preparadas.
6. Comprueba que las entradas Bronze y el YAML mantuvieron su contenido durante la preparación.
7. Llama a Load para guardar los Parquet y los JSON, y devuelve los metadatos de las salidas.
8. Registra el resultado y cierra el manejador del archivo log para evitar duplicaciones en un notebook.

Los comandos `--fuente educacion`, `--fuente poblacion`, `--fuente divipola` y `--fuente internet` siguen preparando únicamente su fuente en memoria. El modo `--silver` es independiente y no se combina con `--fuente`.

### `src/transform/quality_silver.py`

`construir_reporte_silver(tablas, reportes, configuracion, ejecucion_id)` valida que están las cuatro fuentes y que los reportes corresponden a sus tablas. Detiene la publicación si hay encabezados repetidos, columnas esenciales ausentes, llaves incompletas/duplicadas, códigos inválidos o años fuera del periodo.

También comprueba tipos: códigos y estados textuales, años enteros, indicadores educativos decimales, conteos poblacionales y de accesos enteros, y banderas booleanas. Una columna con el texto `"95"` no se publica como si fuera un indicador decimal.

Por fuente registra filas, llave, códigos distintos, distribución por año, tipos, faltantes, estados y banderas. Conserva completo el reporte producido por cada transformador, incluidos sus ejemplos, notas, correcciones y excepciones.

### `src/load/execution_metadata.py`

`capturar_entradas(...)` calcula tamaño y SHA-256 de cada original leyendo bytes por bloques. `crear_metadata_silver(...)` contrasta las huellas tras la preparación e identifica la configuración y el código empleados.

La fecha de modificación del archivo se identifica como tal, en UTC. No se presenta como fecha de descarga o de actualización de la fuente. Las fechas de descarga y versiones de fuente desconocidas permanecen `null`.

Se registran el commit Git disponible, la existencia de cambios locales y las huellas de `main.py`, los módulos de `src/` y el contrato. Si Git no está disponible, sus campos permanecen desconocidos; las huellas de los archivos siguen aportando trazabilidad.

### `src/load/export_results.py`

`exportar_silver(tablas, reporte_calidad, metadata, configuracion, raiz_proyecto)` recibe datos terminados. No repite limpieza ni cambia sus valores.

Su secuencia es:

1. Validar rutas, nombres, extensiones y colisiones. Las salidas quedan dentro del proyecto y no sobrescriben Bronze, Gold o una entrada configurada.
2. Preparar los cuatro Parquet y ambos JSON en una carpeta temporal del proyecto.
3. Reabrir cada Parquet y comparar exactamente valores, tipos, filas y faltantes con la tabla de origen.
4. Añadir a los metadatos rutas, tamaños, esquemas y SHA-256 de las salidas.
5. Conservar respaldos temporales de los seis archivos anteriores, si existen.
6. Reemplazar las salidas y publicar los metadatos al final.
7. Retirar los temporales; si una publicación falla, restaurar las salidas ya reemplazadas.

Si la preparación o la verificación falla, no publica las nuevas tablas. Si el sistema impide también restaurar un respaldo, conserva su carpeta e informa la ubicación para poder recuperar el contenido.

La fecha `fin_exportacion_utc` se captura después de verificar los Parquet, antes de publicar los JSON. Todos los archivos publicados comparten el mismo identificador de ejecución a través del reporte y los metadatos. No se incluye una huella del propio JSON de metadatos dentro de sí mismo, porque sería circular.

## 4. Cómo interpretar el reporte de calidad

El reporte tiene `etapa = silver`, `estado = exploratorio` y `controles_estructura = superados`. Esto significa que las tablas se prepararon y tienen estructura válida para guardarse; no significa que se hayan resuelto todas las incidencias analíticas.

Cada variable crítica presente en una fuente tiene dos medidas locales:

```text
presencia numérica local = cantidades presentes y finitas / filas de esa fuente × 100
utilización local = cantidades que superan los controles de esa fuente / sus filas × 100
```

Se guardan los numeradores y denominadores junto a los porcentajes. Un conjunto vacío tiene porcentaje `null`.

Ejemplos:

- Una cobertura neta de 105 puede estar numéricamente presente y quedar pendiente de revisión; no cuenta como utilizable.
- Una población total cero puede ser un conteo observado válido. Cuenta como dato presente, pero su bandera de uso como denominador para ratios es falsa.
- Un acceso T4 pendiente por segmento puede tener suma numérica. Esa presencia no elimina la revisión semántica.
- Un subtotal `accesos_validos_parcial` no sustituye un total `accesos_t4` faltante.
- Un catálogo disponible no acredita automáticamente la vigencia histórica de sus códigos.

**Los denominadores locales de población e internet no son el denominador del panel integrado.** Para las seis variables críticas del contrato, la aceptación del panel requerirá todas las filas del universo educativo, conservando también las ausencias.

Por eso `aceptacion_panel` contiene:

| Campo | Estado en este punto |
|---|---|
| `estado` | `no_evaluada`. |
| `filas_universo_educativo` | Número calculado de filas educativas. |
| `variables_criticas` | Las seis variables del contrato. |
| `umbrales_pct` | Metas configuradas de 95 %. |
| `homologacion_panel` | `null`: aún no se implementa la homologación del panel. |
| `completitud_seis_variables` | `null`: requiere integrar fuentes y evaluar su utilización. |
| `completitud_conjunta` | `null`: no equivale al conjunto de tres indicadores educativos. |
| `coincidencia_internet_t4` | `null`: se evaluará sobre el panel conservado. |

Los reportes de cada transformador y las columnas de estados siguen mostrando los casos pendientes. No se limita automáticamente cobertura a 100, no se imputan ceros y no se cambian códigos históricos para mejorar artificialmente porcentajes.

## 5. Cómo ejecutar y consultar los resultados

Desde la raíz de `ProyectoFinalETL`:

```powershell
# Preparar las cuatro fuentes y guardar Silver junto con sus evidencias.
.\venv\Scripts\python.exe main.py --silver

# Ejecutar las comprobaciones de todas las etapas implementadas.
.\venv\Scripts\python.exe -m pytest tests -q
```

El proceso completo puede tardar varios minutos por el control global del CSV de internet. Los mensajes de avance también quedan en el log. Otra ejecución completa reemplaza los cuatro Parquet y los dos JSON por una nueva versión coherente; el log conserva el historial.

Para estudiar los archivos sin volver a procesar Bronze, en un notebook abierto en la raíz:

```python
import json
from pathlib import Path
import pandas as pd

# Parquet recupera los tipos y conserva el cero inicial del codigo.
educacion = pd.read_parquet("data/silver/educacion_limpia.parquet")
internet = pd.read_parquet("data/silver/internet_municipio_anio.parquet")

# Inspeccionar las filas y los estados que siguen pendientes.
display(educacion.head())
display(internet[internet["estado_internet"] == "pendiente_revision"])

# Leer el reporte estructurado para consultar controles y denominadores.
calidad = json.loads(Path("logs/reporte_calidad.json").read_text(encoding="utf-8"))
print(calidad["fuentes"]["educacion"]["criticas_en_fuente"])
print(calidad["aceptacion_panel"])
```

## 6. Verificación y continuidad

`tests/test_silver.py` utiliza tablas tipadas y carpetas temporales. Comprueba reglas de calidad, tipos, ceros, faltantes, rutas, hashes, relectura exacta y restauración ante fallos. La prueba del selector de terminal no recorre las fuentes reales; la ejecución completa se verifica por separado.

La verificación final aprobó **216 pruebas**: 51 de Silver y 165 de las cuatro fuentes. También se ejecutó correctamente `main.py --silver` con las entradas reales. La ejecución publicada tiene identificador `457c17ca-dbde-40c5-b70d-eaee1dfd3a08` y tardó aproximadamente cuatro minutos y medio en este equipo.

| Silver publicado | Filas | Columnas | Tamaño en bytes |
|---|---:|---:|---:|
| Educación | 7.850 | 55 | 956.258 |
| Población | 7.861 | 27 | 502.430 |
| Internet | 7.815 | 25 | 269.420 |
| DIVIPOLA | 1.122 | 23 | 102.450 |

Las cantidades son el resultado de esta ejecución, no constantes escritas en el programa. La comprobación posterior reabrió los archivos publicados, revisó sus llaves y esquemas y verificó los hashes de los cuatro Parquet, el reporte de calidad, las entradas Bronze, el YAML y los archivos de código descritos en los metadatos. No quedaron carpetas de staging y Gold conserva su estado anterior.

| Variable crítica | Filas de su fuente | Presencia numérica local | Utilizables según controles locales |
|---|---:|---:|---:|
| Cobertura neta | 7.850 | 100 % | 87,46 % |
| Deserción | 7.850 | 99,94 % | 99,94 % |
| Reprobación | 7.850 | 99,94 % | 99,94 % |
| Población total | 7.861 | 100 % | 99,64 % |
| Población centros/rural | 7.861 | 100 % | 99,64 % |
| Accesos T4 | 7.815 | 100 % | 98,09 % |

Se conservaron 984 coberturas netas pendientes, cinco faltantes de deserción y cinco de reprobación. Población conserva 28 filas con revisión histórica y 11 totales cero; ninguno de esos ceros habilita división. Internet conserva 149 filas pendientes: 132 por segmentos y 17 por territorio. Las 1.122 filas del catálogo superan sus controles locales; su vigencia histórica sigue sin acreditarse automáticamente.

Los tres Silver anuales mantienen `estado_homologacion = pendiente_revision`. La tabla de porcentajes anterior no acredita el 95 % exigido para el panel. En particular, la cobertura neta ya muestra una limitación local que habrá que resolver o mantener explícita al evaluar ese panel.

El siguiente punto será implementar `integrate_sources.py` usando las tablas Silver: conservar el universo educativo, unir por llaves con controles de cardinalidad, distinguir ausencias y resolver o mantener explícitas las excepciones. Solo entonces se evaluarán homologación y completitud del panel y se avanzará a indicadores Gold.
