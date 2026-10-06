# Extracción y limpieza de internet fijo

Fecha: 2026-10-06. Esta etapa completa el cuarto componente del punto 3: preparar las fuentes de forma independiente. Entrada: `data/bronze/ACCESOS_INTERNET_FIJO_2_8.csv`, conservada sin modificaciones.

## 1. Qué representa una fila

Una fila del CSV es un reporte detallado de accesos por año, trimestre, empresa, territorio, segmento, tecnología y velocidades de bajada y subida. No equivale al total de un municipio. El [diccionario oficial de Postdata](https://www.postdata.gov.co/resource/accesos-de-internet-fijo-desde-2017-2t) describe estos campos y el conteo de accesos al cierre del trimestre.

La salida preparada tiene una fila por `codigo_municipio + anio`, con la suma observada de los reportes territoriales del cuarto trimestre. Incluye áreas no municipalizadas; el nombre de la llave se mantiene para compatibilidad con las otras fuentes.

T4 representa una observación al cierre del año. **No sumamos T1 + T2 + T3 + T4:** eso sumaría existencias de momentos diferentes. Si falta T4, tampoco sustituimos por T3 ni inventamos un cero.

Ejemplo: dos reportes distintos de Medellín en T4, uno con 10 accesos DSL y otro con 20 accesos de cable, aportan 30 al total observado. Un reporte de T3 con 900 accesos queda fuera de esa suma. Este ejemplo supone categorías compatibles; las categorías ambiguas se señalan para revisión.

## 2. Responsabilidad de cada archivo

### `src/extract/extract_internet.py`

`extraer_internet(configuracion_fuente, raiz_proyecto)` valida la entrada y devuelve un generador de DataFrames:

1. Obtiene ruta, separador, codificación y tamaño de bloque desde el YAML.
2. Verifica que existe el CSV y que el encabezado no repite nombres ni omite campos obligatorios.
3. Exige lectura como texto y conserva las quince columnas de la fuente.
4. Lee bloques de 100.000 registros. No filtra datos, no concatena todo el archivo ni lo cambia.
5. Guarda archivo, opciones, número de bloque y ordinal inicial en `bloque.attrs["origen_csv"]`.
6. Cierra el lector al terminar o al cerrar el generador. Una fecha de descarga desconocida permanece desconocida.

Un generador entrega un bloque cuando el transformador lo solicita. Así se controla la memoria utilizada por un archivo de aproximadamente 441 MB y más de tres millones de registros. **No debe convertirse en `list(...)` con la fuente completa.**

El literal `NA` de la columna `TECNOLOGIA` se conserva como texto. Solo los campos vacíos se leen como faltantes. Esto evita perder una categoría observada por una interpretación automática de pandas.

### `src/transform/clean_internet.py`

`limpiar_internet(bloques, configuracion)` consume los bloques una sola vez y devuelve `(internet_anual, reporte)`:

1. Comprueba las reglas del contrato y trabaja sobre una copia de cada bloque.
2. Conserva códigos y nombres territoriales originales y el ordinal del registro CSV. Ese ordinal no es una línea física del archivo.
3. Valida año, trimestre e identificadores antes de seleccionar el periodo. Una llave incompleta no se oculta mediante un filtro.
4. Normaliza códigos territoriales válidos como texto: `5001 → 05001`, `5 → 05`.
5. Identifica nacionales contrastando código cero y nombres de municipio/departamento. El municipio Colombia, Huila (`41206`), permanece territorial.
6. Convierte los accesos a enteros exactos no negativos, con tipo anulable `Int64`.
7. Revisa metadatos de velocidades y construye una representación decimal exacta para la llave de reporte; todavía no calcula indicadores de velocidad.
8. Detecta llaves detalladas repetidas en todo el CSV, incluso entre bloques o fuera de 2018–2024/T4.
9. Selecciona territoriales de 2018–2024, exclusivamente T4, y revisa categorías declaradas como totales.
10. Acumula contribuciones por código y año, conservando variantes de nombres, segmentos, tecnologías y marcas de revisión.
11. Devuelve la tabla anual con estados y un reporte de conciliación.

El patrón conserva la separación de extracción, transformación y coordinación del ejemplo `proyecto_final_2026`, adaptada al volumen y al contrato del proyecto.

### `main.py`

`ejecutar_internet()` carga la configuración compartida, abre el generador, llama al transformador y devuelve tabla y reporte. `closing(...)` garantiza cerrar el generador aunque una validación detenga el proceso.

`--fuente internet` muestra los controles y una muestra anual. Las otras fuentes siguen disponibles; sin argumento, el comando continúa preparando educación.

### `config/config.yaml`

Se completaron los quince encabezados obligatorios, incluidos los identificadores de empresa y segmento necesarios para reconocer un reporte. Se añadieron los segmentos conocidos, el segmento pendiente `117` y los códigos territoriales por revisar. Se mantienen las reglas acordadas: bloques de 100.000, periodo 2018–2024, T4 exclusivo, sin imputación, velocidad/fibra desactivadas y rutas relativas al proyecto.

## 3. Cómo evitamos duplicar o alterar conteos

La llave detallada de un reporte es:

```text
año + trimestre + ID_EMPRESA + código municipal
+ ID_SEGMENTO + ID_TECNOLOGIA + velocidad de bajada + velocidad de subida
```

El código departamental se revisa contra el prefijo municipal. Los nombres descriptivos no crean reportes nuevos y **ACCESOS no forma parte de esta llave**: cambiar una cantidad para el mismo detalle produce una ambigüedad, no una nueva contribución.

Las velocidades `2`, `2.0`, `2,0` y `02.00` representan el mismo número para comprobar unicidad. Se usa `Decimal` sin redondeo para reconocerlo. Esta equivalencia de escritura no convierte unidades.

Un conjunto de llaves de millones de filas ocuparía mucha memoria. Por eso se utiliza un archivo SQLite temporal con una llave única exacta. Su índice detecta duplicados entre cualquier par de bloques. No usa una huella aproximada y no elimina ni suma filas repetidas: un duplicado detiene la etapa.

SQLite se crea en la carpeta temporal del sistema, se cierra y se elimina al terminar o fallar. Es un control de esta ejecución, no un destino Load ni un archivo Silver del proyecto.

Los conteos se convierten desde el texto mediante `Decimal`: una fracción diminuta sigue siendo inválida y un entero grande conserva sus dígitos. La suma por municipio utiliza enteros de Python y comprueba el límite de `Int64` antes de producir la tabla. El resumen anual también suma con enteros de Python para evitar desbordamientos silenciosos.

## 4. Columnas y estados principales

| Columna | Significado |
|---|---|
| `codigo_municipio`, `anio` | Llave única anual. |
| `codigo_departamento`, `municipio`, `departamento` | Metadatos observados; no nombres históricos homologados. |
| `accesos_t4` | Suma observada de T4 cuando todas las contribuciones tienen accesos válidos. |
| `accesos_validos_parcial` | Subtotal de contribuciones válidas, exclusivamente para diagnóstico. |
| `trimestre_referencia` | 4 en toda fila preparada. |
| `registros_fuente` | Número de reportes detallados que aportaron a esa llave anual. |
| `registros_accesos_no_utilizables` | Contribuciones con conteos vacíos, inválidos, fraccionarios o negativos. |
| `registro_origen_min`, `registro_origen_max` | Ordinales extremos del grupo; el CSV original conserva el detalle completo. |
| `revision_territorial_pendiente` | Código incluido en los casos históricos por revisar. |
| `departamento_inconsistente` | Código departamental inválido o diferente del prefijo municipal. |
| `metadatos_reporte_pendientes` | Nombres/categorías faltantes o velocidades no numéricas, negativas o no finitas. |
| `segmento_pendiente_revision` | Segmento `117` o identificador de segmento no reconocido. |
| `estado_internet` | `disponible`, `pendiente_revision` o `no_utilizable`. |
| `accesos_para_indicadores_utilizables` | Verdadero únicamente cuando supera estos controles de la fuente. |
| `estado_homologacion` | `pendiente_revision`: la integración territorial todavía no se ha implementado. |

Las columnas `codigos_municipio_originales`, `nombres_municipio_originales`, `codigos_departamento_originales`, `nombres_departamento_originales`, `segmentos_originales` y `tecnologias_originales` guardan listas JSON con variantes observadas. El CSV Bronze conserva todas las filas originales, empresas, velocidades y cantidades; la tabla anual es un resumen.

Un cero reportado sigue siendo cero. Si una contribución del grupo es inválida, `accesos_t4` queda faltante y `estado_internet = no_utilizable`. El subtotal válido no se presenta como total: `10 + dato inválido` produce total faltante y subtotal diagnóstico 10. Si ninguna contribución es válida, tampoco se inventa un subtotal cero.

Si todas las cantidades son válidas pero existe una incidencia semántica, se conserva la suma y se marca `pendiente_revision`. **Tener una cifra no equivale a autorizar su uso en indicadores.** La bandera de accesos tampoco acredita una homologación territorial resuelta ni un denominador poblacional utilizable.

Esta tabla independiente contiene solamente llaves con reporte T4. En la futura integración se conservará el universo educativo mediante una unión izquierda y se marcarán sus ausencias como `sin_reporte_t4`. No crear esa fila aquí evita atribuir a internet un universo territorial inventado.

## 5. Excepciones que se conservan

### Segmento 117

El CSV incluye `Corporativo  (accesos adicionales)`, ID `117`: 438 reportes en la selección T4. Su relación histórica con el segmento corporativo `107` no quedó acreditada para la versión disponible del archivo.

El formato T.1.3 de la [Resolución CRC 6333 de 2021 original](https://www.crcom.gov.co/sites/default/files/webcrc/micrositios/documents/Resoluci%C3%B3n-CRC-6333-de-2021.pdf) presenta los segmentos corporativo, sin estratificar e interno, sin la categoría adicional `117`. El [documento de simplificación regulatoria de diciembre de 2024](https://www.crcom.gov.co/system/files/Proyectos%20Comentarios/2000-38-3-22/Propuestas/documento-soporte-simplificacion-regulatoria-201224.pdf), página 168, propone esa categoría. Los metadatos actuales y las definiciones posteriores no bastan para resolver automáticamente los registros históricos de este CSV.

La decisión conservadora es mantener las cantidades observadas y marcar todos los grupos que contienen `117` como pendientes. No se elimina el segmento, no se resta de `107` y no se presupone que ya quedó resuelta su exclusividad. Los resúmenes anuales incluyen esas cantidades para conciliar la fuente, no para certificar un total semánticamente aprobado.

### Territorios históricos

Se señalan `27086`, `27493`, `27615`, `94343` y `94663`. Se conservan sus códigos y cantidades; no se transfieren accesos entre territorios.

En particular, el CSV tiene Belén de Bajirá (`27086`) con 2 accesos en 2018 y 4 en 2019. Son dos llaves ausentes del universo educativo y del catálogo actual. **No se reasignan a Nuevo Belén de Bajirá (`27493`).** Los cambios geográficos siguen pendientes de reglas y evidencia histórica.

### Velocidad y fibra

El diccionario actual describe velocidades en Mbps, pero el CSV presenta extremos que necesitan conciliarse con la versión y significado histórico de la fuente. Esta etapa valida la escritura y utiliza velocidades para distinguir reportes. No calcula promedios ni convierte automáticamente esos extremos.

La participación de fibra también permanece desactivada hasta verificar el conjunto de códigos, el denominador y los accesos de tecnología desconocida. Los 15 reportes T4 cuya tecnología literal es `NA` se conservan.

## 6. Resultado de la fuente real

| Control | Resultado |
|---|---:|
| Filas originales revisadas | 3.288.251 |
| Bloques leídos | 33 |
| Filas fuera de 2018–2024 | 684.132 |
| Otros trimestres dentro de 2018–2024 | 1.938.951 |
| Nacionales T4 del periodo | 0 |
| Reportes territoriales T4 seleccionados | 665.168 |
| Llaves territorio-año preparadas | 7.815 |
| Códigos territoriales distintos en la salida | 1.123 |
| Llaves detalladas duplicadas en todo el CSV | 0 |
| Contribuciones con accesos no utilizables | 0 |
| Reportes T4 con accesos cero | 1.156 |
| Reportes T4 con tecnología literal `NA` | 15 |
| Filas anuales con `estado_internet = disponible` | 7.666 |
| Filas anuales con `estado_internet = pendiente_revision` | 149 |
| Filas anuales con segmento pendiente | 132 |
| Filas anuales con revisión territorial | 17 |
| Filas anuales con departamento inconsistente o metadatos pendientes | 0 |

Las tres filas nacionales identificadas en el archivo corresponden a 2017, fuera del periodo. Los conteos de filas fuera de periodo, otros trimestres del periodo, nacionales T4 del periodo y T4 territoriales concilian exactamente las filas de entrada.

Las 438 contribuciones del segmento `117` aparecen en 132 llaves anuales. Las otras 17 pendientes son territoriales: `27086` en dos años, `27493` en uno, `27615` en siete y `94343` en siete. No hay reporte territorial T4 seleccionado de `94663`. En esta fuente las dos causas de revisión no se superponen; 132 + 17 = 149. Ninguna fila anual tiene cantidades no utilizables.

| Año | Reportes T4 | Territorios | Suma observada de accesos |
|---|---:|---:|---:|
| 2018 | 62.368 | 1.108 | 6.731.666 |
| 2019 | 77.860 | 1.116 | 6.984.242 |
| 2020 | 87.073 | 1.118 | 7.837.355 |
| 2021 | 103.916 | 1.117 | 8.454.845 |
| 2022 | 110.439 | 1.118 | 8.841.612 |
| 2023 | 113.846 | 1.116 | 9.064.552 |
| 2024 | 109.666 | 1.122 | 9.278.294 |

Son sumas de las cantidades observadas, incluidos casos pendientes. Ejemplo de conciliación: Medellín 2024 tiene 791.436 accesos a partir de 1.618 reportes T4.

La selección coincide con la agregación T4 explorada en `analisis_poblacion.ipynb` y el examen de la fuente en `analisis_internet.ipynb`. La conciliación independiente compara todas las 7.815 llaves y cantidades, además de los totales anuales. La huella SHA-256 del CSV se comprueba antes y después de la ejecución.

Verificación real completada: las 7.815 llaves y cantidades coinciden exactamente con una lectura independiente de las cuatro columnas año, trimestre, código y accesos. La huella antes y después fue `2fa895b0bb5d19c946c5f9c6f060e9de4036281a27c29c7e5a35243600d6bb5e`. El proceso de preparación tardó aproximadamente cuatro minutos en esta ejecución; el tiempo puede variar según el equipo.

Los cruces diagnósticos con educación dan 7.813 coincidencias de sus 7.850 llaves y 37 sin reporte T4: 99,53 % de coincidencia. Las otras dos llaves de internet son `27086`, 2018 y 2019. Este porcentaje mide presencia, no completitud semántica ni homologación resuelta. Los cruces son controles en memoria; todavía no crean Gold.

Con población coinciden 7.813 llaves. Frente al catálogo DIVIPOLA, el único código presente en esta salida y ausente del catálogo es `27086`. Estas comprobaciones no reasignan códigos ni cambian las tablas de las otras fuentes.

## 7. Cómo ejecutar y estudiar el código

Desde la raíz de `ProyectoFinalETL`, en PowerShell:

```powershell
# Preparar internet y mostrar sus controles; puede tardar unos minutos.
.\venv\Scripts\python.exe main.py --fuente internet

# Verificar las cuatro fuentes implementadas.
.\venv\Scripts\python.exe -m pytest tests/test_education.py tests/test_population.py tests/test_divipola.py tests/test_internet.py -q
```

En un notebook abierto en la raíz:

```python
# Importar la coordinacion no ejecuta automaticamente el CSV.
from main import ejecutar_internet

# Obtener el resumen anual y su reporte; el CSV se procesa por bloques.
internet, reporte = ejecutar_internet()

# Consultar cantidades y distinguir los casos pendientes.
display(internet.head())
print(reporte["estados_internet"])
display(internet[internet["estado_internet"] == "pendiente_revision"])
```

Para estudiar el flujo, leer primero `main.py`, después el extractor y finalmente el transformador. Los comentarios explican las decisiones y los ejemplos de `tests/test_internet.py` muestran los casos límite.

Las pruebas usan tablas sintéticas y CSV temporales. Comprueban lectura incremental, conservación, encabezados, T4, nacionales, códigos, suma entre bloques, duplicados globales, categorías, faltantes, ceros, precisión, desbordamientos, JSON y selección del comando. La verificación conjunta aprobó 165 casos: 61 de internet y 104 de las etapas anteriores.

## 8. Qué queda después

La tabla y el reporte quedan en memoria. El siguiente punto es implementar la escritura controlada de los cuatro Silver y sus reportes de calidad. La ruta ya configurada para esta fuente es `data/silver/internet_municipio_anio.parquet`; en esta etapa aún no se genera.

Después se implementará la integración por código y año conservando el universo educativo, los faltantes, los extras y las excepciones. Para indicadores se combinarán las marcas de accesos, población y homologación. La aprobación del software no resuelve automáticamente los segmentos o territorios pendientes.
