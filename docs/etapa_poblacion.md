# Extracción y limpieza de población del DANE

Fecha: 2026-10-05. Este documento explica el segundo componente implementado del punto 3. La fuente es `data/bronze/PPED-AreaMun-2018-2042_VP.xlsx`, hoja `PobMunicipalxÁrea`.

## 1. Qué representa la fuente

El libro contiene una serie de proyecciones municipales por área para 2018–2042. En esta etapa seleccionamos 2018–2024, como establece el contrato. La población se expresa en personas de la serie DANE utilizada; no se presenta como un conteo observado ni como población escolar.

| Columna original | Uso en el ETL |
|---|---|
| `DP` | Código del departamento; texto de dos dígitos. |
| `DPNOM` | Nombre del departamento. |
| `MPIO` | Código territorial; texto de cinco dígitos. |
| `DPMP` | Nombre del municipio o área no municipalizada. |
| `AÑO` | Año de la población. |
| `ÁREA GEOGRÁFICA` | Categoría: total, cabecera o centros poblados/rural disperso. |
| `TOTAL` | Personas de la categoría indicada en esa misma fila. |

**La columna `TOTAL` no significa siempre población total municipal.** En una fila de cabecera significa población de cabecera. Solo la fila cuya categoría es `Total` contiene la población total del territorio.

El encabezado está en la fila visible 8 de Excel: `header=7` en pandas, porque ese índice comienza en cero. La fila 9 está vacía y los datos empiezan en la fila 10. El pie conserva una fuente, dos notas territoriales y el texto `Actualizado el 30 de Julio de 2025`. Esa actualización es información del archivo; no se inventa una fecha de descarga.

## 2. Responsabilidad de los archivos

### `src/extract/extract_population.py`

La función `extraer_poblacion(configuracion_fuente, raiz_proyecto)` realiza la extracción:

1. Resuelve la ruta del YAML respecto a la raíz del proyecto y comprueba que exista el archivo.
2. Comprueba el tipo XLSX, el nombre de hoja, el encabezado y las opciones de lectura.
3. Abre el libro en modo de solo lectura para verificar la hoja y los encabezados originales. Así detecta una columna repetida antes de que pandas la renombre.
4. Lee la hoja como texto, conservando códigos, vacíos y filas de notas.
5. Añade metadatos de procedencia en `datos.attrs["origen_excel"]`: archivo, hoja, encabezado y títulos previos.
6. Devuelve un DataFrame sin limpiar, filtrar ni sobrescribir Bronze.

No se usan `skiprows`, `skipfooter`, `nrows`, `usecols` ni `index_col`: esas opciones podrían romper la relación con las filas físicas o quitar evidencia. Las opciones declaradas para esta fuente son suficientes para leerla íntegramente después del encabezado.

### `src/transform/clean_population.py`

La función `limpiar_poblacion(datos_originales, configuracion)` devuelve `(tabla_anual, reporte)`.

Primero crea una copia y normaliza los siete encabezados. Conserva códigos y población originales antes de quitar espacios, y asigna `fila_excel` a cada registro.

Después separa dos clases de filas ajenas a la tabla:

- Filas completamente vacías.
- Notas reconocidas que ocupan solo `DP` y empiezan por `Fuente:`, `Nota:` o `Actualizado`.

Una fila que solo contiene un código departamental no se considera una nota. Se conserva en la revisión y falla por año incompleto; así no desaparece un registro mal formado. Las notas se guardan como texto y fila física en `reporte["notas_archivo"]`.

La función valida años antes de filtrar 2018–2024, normaliza códigos válidos y se detiene si una llave municipal está incompleta. Los códigos cero no se convierten en municipios. Conserva las áreas no municipalizadas.

Antes de cambiar la forma de la tabla comprueba:

- Categorías de área reconocidas y no vacías.
- Unicidad de `codigo_municipio + anio + area_geografica`.
- Concordancia del departamento y los nombres entre las áreas del mismo territorio–año.

Las llaves duplicadas o los metadatos contradictorios detienen la etapa. No se elige una fila arbitraria ni se agregan registros repetidos.

La población se convierte a `Int64`, un entero que permite faltantes. Textos no convertibles, infinitos, negativos o fracciones quedan faltantes en el campo limpio y se reportan; el original permanece. Los ceros observados se conservan. No se aplica la regla de puntos y comas del CSV educativo: el Excel real ya contiene conteos enteros.

## 3. Por qué hacemos un pivote

La fuente tiene formato largo: tres filas por territorio–año. Para unirla posteriormente con educación necesitamos una sola fila por la misma llave.

Ejemplo de Medellín 2024 en la fuente:

| Código | Año | Área | TOTAL |
|---|---:|---|---:|
| 05001 | 2024 | Cabecera Municipal | 2.476.134 |
| 05001 | 2024 | Centros Poblados y Rural Disperso | 48.613 |
| 05001 | 2024 | Total | 2.524.747 |

El resultado preparado es:

| codigo_municipio | anio | poblacion_total | poblacion_cabecera | poblacion_centros_rural |
|---|---:|---:|---:|---:|
| 05001 | 2024 | 2.524.747 | 2.476.134 | 48.613 |

Se usa `pivot`, que cambia la disposición de valores sin sumarlos. **No sumamos las tres categorías:** el total ya contiene sus dos componentes y esa suma duplicaría la población.

Las columnas se crean siempre, incluso si una categoría falta en toda la entrada. Una ausencia permanece faltante; no se reconstruye un total sumando componentes ni se supone que un área ausente tiene cero habitantes.

## 4. Comprobaciones y trazabilidad

La tabla anual conserva:

- `poblacion_total`, `poblacion_cabecera`, `poblacion_centros_rural`.
- El texto original de cada conteo en las correspondientes columnas `*_original`.
- `fila_excel_total`, `fila_excel_cabecera`, `fila_excel_centros_rural` para localizar cada dato en Bronze.
- Los códigos originales de la fila `Total` en `codigo_municipio_original` y `codigo_departamento_original`. Si esa fila falta, esos originales quedan faltantes; las referencias de los componentes siguen disponibles.
- Nombres de municipio y departamento procedentes de la fuente, sin homologación automática por similitud.

Calculamos dos controles, sin generar todavía indicadores Gold:

```text
suma_componentes = poblacion_cabecera + poblacion_centros_rural
diferencia_componentes = poblacion_total - suma_componentes
```

Si todas las poblaciones son utilizables y la diferencia es cero, `poblacion_consistente` es verdadera. Si son utilizables pero no suman, es falsa. Si algún conteo falta o no puede utilizarse, permanece faltante: no se presenta como una comprobación exitosa ni se inventa un componente.

Los componentes numéricos válidos son no negativos; junto con la igualdad anterior, esto exige que cada componente no supere el total.

Otras marcas son `areas_incompletas`, `departamento_inconsistente`, `metadatos_incompletos` y `revision_territorial_pendiente`. El reporte distingue áreas ausentes de áreas presentes con un conteo faltante.

## 5. Estados, ceros y casos históricos

| Campo o estado | Significado |
|---|---|
| `estado_poblacion = disponible` | Conteos y componentes válidos según los controles iniciales; sin incidencias territoriales señaladas. |
| `estado_poblacion = pendiente_revision` | Conteos conservados, pero existe un caso territorial o metadato que debe revisarse. |
| `estado_poblacion = no_utilizable` | Falta un conteo utilizable o los componentes no concuerdan. |
| `denominador_positivo` | El total es numérico y mayor que cero. |
| `poblacion_para_ratios_utilizable` | Además de total positivo, el conjunto está `disponible`. |
| `estado_homologacion = pendiente_revision` | Todavía no se ha comprobado la identidad con DIVIPOLA o una regla histórica respaldada. |

Un cero válido puede formar parte de un conjunto consistente; no permite dividir por él. La disponibilidad de población y la homologación son controles distintos.

En `sources.population.territorial_review_codes` del YAML se declaran los cuatro casos ya identificados en el contrato:

| Código | Territorio | Evidencia y tratamiento inicial |
|---|---|---|
| 27493 | Nuevo Belén de Bajirá | La nota describe su creación y segregación de Riosucio. La serie contiene total cero en 2018–2023 y 29.812 en 2024. |
| 27615 | Riosucio | Su serie requiere revisar los efectos del cambio territorial; no transferimos población a otro código. |
| 94343 | Barrancominas | La nota describe su creación integrando las áreas de Barrancominas y Mapiripana. |
| 94663 | Mapiripana | Su serie contiene total cero desde 2020; conservamos esos registros. |

La marca se aplica conservadoramente a los siete años del periodo de cada código: 28 registros. No demuestra que sus conteos sean erróneos ni resuelve la vigencia histórica del territorio. Los valores se mantienen, pero no se habilitan automáticamente para ratios antes de la revisión.

## 6. Cómo ejecutar la etapa

Desde la raíz de `ProyectoFinalETL`, en PowerShell:

```powershell
# Elegir población sin ejecutar otras fuentes ni escribir salidas.
.\venv\Scripts\python.exe main.py --fuente poblacion

# El comando anterior de educación sigue disponible.
.\venv\Scripts\python.exe main.py --fuente educacion

# Verificar las dos etapas ya implementadas.
.\venv\Scripts\python.exe -m pytest tests/test_education.py tests/test_population.py -q
```

Sin `--fuente`, el comando sigue preparando educación. `main.py` encuentra su raíz mediante `__file__`, por lo que también admite ejecución desde otra carpeta. `--config` permite indicar otro YAML.

En un notebook abierto en la raíz del proyecto:

```python
# Importar el módulo no ejecuta automáticamente el proceso.
from main import ejecutar_poblacion

# La función devuelve la tabla anual y sus controles por separado.
poblacion, reporte = ejecutar_poblacion()

# Consultar valores preparados y notas preservadas del Excel.
display(poblacion.head())
print(reporte["estados_poblacion"])
print(reporte["notas_archivo"])
```

La etapa trabaja en memoria. La escritura de `data/silver/poblacion_limpia.parquet` se incorporará en el punto 4 mediante el módulo de carga. No se genera Gold ni se calcula todavía ruralidad o accesos por habitante. Los mensajes se muestran en consola; los archivos persistentes de log y reporte llegarán con la ejecución completa.

## 7. Resultado de referencia y conciliación

| Control | Resultado de la fuente actual |
|---|---:|
| Filas leídas después del encabezado | 84.234 |
| Filas vacías separadas | 5 |
| Notas conservadas | 4 |
| Filas de datos de 2018–2042 | 84.225 |
| Filas tabulares fuera de 2018–2024 | 60.642 |
| Filas seleccionadas por área | 23.583 |
| Filas anuales preparadas | 7.861 |
| Territorios por cada año del periodo | 1.123 |
| Llaves duplicadas, áreas incompletas o sumas inconsistentes | 0 |
| Poblaciones totales en cero | 11 |
| Poblaciones de cabecera en cero | 141 |
| Poblaciones de centros/rural en cero | 11 |
| Registros disponibles inicialmente | 7.833 |
| Registros territoriales pendientes | 28 |

La tabla se concilia con las celdas de población del notebook `analisis_poblacion.ipynb`, sin ejecutar su instalación de paquetes ni su procesamiento de internet. Las poblaciones, llaves y nombres se contrastan; los nuevos controles y la selección del periodo son explícitos. El original se verifica mediante su huella SHA-256.

En el diagnóstico de coincidencias con educación, sus 7.850 registros encuentran población y tienen total positivo. Las 11 filas adicionales del DANE son los totales cero de Nuevo Belén de Bajirá (2018–2023) y Mapiripana (2020–2024). Se mantienen en la tabla independiente del DANE; la futura unión con MEN conservará su propio universo.

De los 28 casos territoriales pendientes, 17 coinciden con educación. Una coincidencia por código y año no equivale a una identidad histórica resuelta. Estas comprobaciones no publican una tabla integrada ni declaran cumplimiento de la calidad conjunta Gold.

## 8. Pruebas y próximo componente

`tests/test_population.py` comprueba conservación de la fuente y de la entrada, hoja y encabezados, notas, llaves, años, categorías, metadatos, pivote incompleto, conteos inválidos, sumas, ceros, revisión territorial y JSON estricto. Usa datos sintéticos y libros temporales; no escribe sobre el Excel de Bronze.

La verificación final de esta implementación pasó 38 casos de población y 31 de educación: 69 pruebas en conjunto. También se ejecutaron correctamente los comandos de población y de educación.

Educación y población constituyen dos componentes del punto 3. El siguiente componente recomendado es DIVIPOLA: preparar el catálogo para comprobar códigos, departamentos y tipo de territorio, manteniendo aparte los problemas de geografía histórica. Después se abordará internet antes de persistir Silver e integrar Gold.
