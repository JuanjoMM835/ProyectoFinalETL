# Primera implementación: extracción y limpieza de educación

Fecha: 2026-10-05. Esta implementación corresponde al componente educativo del punto 3 del plan. Las otras fuentes, la persistencia Silver y la integración Gold quedan para las etapas siguientes.

## 1. Cómo se utilizó el ejemplo `proyecto_final_2026`

El ejemplo organiza el proceso mediante funciones de extracción, transformación y carga, coordinadas por `main.py`. Se conserva esa estructura y el uso de un DataFrame como tabla de trabajo.

Las reglas de transformación se adaptan al contrato de nuestro proyecto:

| En el ejemplo | En ProyectoFinalETL |
|---|---|
| `extraer_datos()` lee una fuente y devuelve un DataFrame. | `extraer_educacion()` lee Bronze, comprueba encabezados y devuelve la fuente sin limpiarla. |
| `limpiar_datos()` transforma los registros. | `limpiar_educacion()` devuelve una tabla limpia y un reporte de controles. |
| Se eliminan duplicados y se imputan algunos faltantes. | Las llaves repetidas detienen la etapa; los faltantes se conservan, sin imputación. |
| Se escriben archivos y un gráfico desde la transformación. | La limpieza funciona en memoria; escribir Silver corresponderá al módulo de carga del punto 4. |
| Algunas rutas son personales y absolutas. | `main.py` obtiene la raíz desde `__file__` y resuelve las rutas del YAML desde allí. |
| Existe un módulo de integración de estudiantes e historial. | La integración territorial se implementará después de limpiar las fuentes restantes. |

El proyecto de ejemplo se revisó como referencia y no se modificó. Sus imputaciones de medias, columnas de estudiantes y gráficos no se trasladan a indicadores municipales.

## 2. Responsabilidad de cada archivo

### `src/extract/extract_education.py`

La función `extraer_educacion(configuracion_fuente, raiz_proyecto)`:

1. Comprueba que se declaró una fuente CSV y que el archivo existe.
2. Obtiene separador, codificación y tipos del YAML.
3. Comprueba el encabezado original para detectar columnas repetidas o ausentes.
4. Lee todas las filas y columnas del MEN como texto.
5. Devuelve el DataFrame; no modifica Bronze ni rellena datos.

### `src/transform/clean_education.py`

La función `limpiar_educacion(datos_originales, configuracion)` devuelve dos objetos:

```python
# La tabla preparada y su evidencia de calidad se mantienen separadas.
datos_limpios, reporte = limpiar_educacion(datos_originales, configuracion)
```

Su secuencia es:

1. Trabajar sobre una copia de la entrada.
2. Normalizar encabezados: `AÑO` pasa a `anio`; `CÓDIGO_MUNICIPIO` pasa a `codigo_municipio`.
3. Guardar `registro_origen` y columnas originales relevantes antes de transformar valores. El ordinal identifica el registro de datos, no la línea física del CSV.
4. Quitar espacios y reconocer campos vacíos.
5. Verificar que el año sea legible, entero y positivo antes de filtrar.
6. Identificar nacionales contrastando código, municipio y departamento. Colombia, Huila (`41206`), sigue siendo un municipio.
7. Seleccionar 2018–2024 y separar nacionales.
8. Normalizar códigos mediante grupos de dígitos válidos. Conservar códigos ETC como identificadores textuales, sin aplicarles la longitud municipal.
9. Detenerse ante llaves municipales incompletas o repetidas.
10. Convertir los campos numéricos conocidos; conservar columnas desconocidas como texto y reportarlas.
11. Tratar separadores de miles únicamente en población escolar, con grupos completos de tres dígitos.
12. Añadir estados de uso de las tasas y controles de departamento y población escolar.
13. Devolver la tabla y un reporte que distingue presencia numérica de utilización semántica.

Los indicadores numéricos conservan faltantes mediante tipos anulables (`Float64` e `Int64`). Los códigos utilizan `string` para conservar ceros iniciales.

### `main.py`

La función `ejecutar_educacion()` lee el YAML, llama al extractor y al transformador, y devuelve `(datos, reporte)` en memoria. `main()` permite ejecutar esa secuencia desde terminal y muestra un resumen y cinco filas de ejemplo.

El nivel y formato de los mensajes vienen de la configuración. En esta etapa los mensajes se muestran en consola; no se exportan todavía los archivos de reporte ni el log persistente previstos para la ejecución completa.

No se llama aún al módulo de carga. La ejecución actual no genera Silver ni Gold y no demuestra homologación con DIVIPOLA. `estado_homologacion` permanece `pendiente_revision` hasta verificar la identidad territorial.

## 3. Cómo ejecutar y consultar el resultado

Desde la raíz de `ProyectoFinalETL`, en PowerShell:

```powershell
# Usar el Python del entorno virtual del proyecto, sin depender de activar Scripts.
.\venv\Scripts\python.exe main.py
```

El script también puede ejecutarse mediante su ruta absoluta desde otra carpeta. La configuración predeterminada se encuentra respecto a `main.py`.

Para usar la tabla en un notebook abierto en la raíz del proyecto:

```python
# Importar no ejecuta automáticamente el proceso.
from main import ejecutar_educacion

# Esta llamada realiza extracción y limpieza, sin escribir salidas.
educacion, reporte = ejecutar_educacion()

# Consultar los datos y sus controles por separado.
display(educacion.head())
print(reporte["estados_indicadores"])
```

## 4. Diferencias deliberadas frente al notebook exploratorio

El notebook permite revisar la fuente, pero `pd.to_numeric()` por sí solo no interpreta todos los formatos de población escolar ni acredita la validez de una tasa.

- `1,174,274` se convierte a `1174274` conservando el texto original.
- En 2021 aparecen 845 valores con grupos completos de miles separados por puntos, por ejemplo Medellín `379.616`. En el conteo de población se interpretan como `379616`, no como una fracción de persona.
- Hay otros 80 valores fraccionarios o ambiguos de población escolar, como `7.74`. No se multiplican por mil ni se redondean. Se conservan en la columna original y el valor limpio queda faltante, con `poblacion_5_16_no_utilizable = true`.
- Esta regla de miles no se aplica a las tasas: una deserción `5.234` conserva su valor decimal.
- No se truncan poblaciones fraccionarias mediante una conversión a entero.
- Las coberturas netas superiores a 100 conservan su valor y quedan `pendiente_revision`; las coberturas brutas superiores a 100 se reportan como observación informativa, sin recorte automático.

Las reglas de población escolar no sustituyen al denominador de población total DANE, que se incorporará en su propia etapa.

Además, al comparar los años vecinos se detectaron tres conteos enteros sospechosos en 2021:

| Territorio y código | Población escolar 2020 | Texto original 2021 | Población escolar 2022 |
|---|---:|---:|---:|
| Filadelfia — 17272 | 1.988 | `2` | 1.905 |
| Capitanejo — 68147 | 999 | `1` | 994 |
| San Onofre — 70713 | 12.945 | `13` | 13.467 |

Los valores `2`, `1` y `13` se conservan como enteros, pues su formato por sí solo es válido. Esta comparación sugiere una posible pérdida de separadores o cifras, pero no acredita la cifra correcta: los tres casos quedan documentados para revisar la fuente antes de utilizar población escolar en un indicador. No se multiplican por mil ni se imputan con años vecinos. No forman parte de los 80 valores de formato no utilizable. La bandera `poblacion_5_16_no_utilizable` comprueba el formato de conteo; que sea falsa no certifica la exactitud del valor.

## 5. Estados de indicadores

| Estado | Significado |
|---|---|
| `disponible` | Dato numérico utilizable según los controles iniciales de esta etapa. |
| `faltante` | No se dispone de un valor en la fuente. |
| `no_numerico` | Había texto que no pudo convertirse en un número utilizable. |
| `no_utilizable` | El valor incumple una condición necesaria, por ejemplo una tasa negativa o infinita. |
| `pendiente_revision` | El valor se conserva, pero requiere revisión de la definición o de la fuente antes de usarlo. |

Estos estados son controles iniciales y no sustituyen una revisión completa de la metodología del MEN. Una sospecha de rango no se convierte automáticamente en una corrección del dato.

## 6. Referencias para verificar esta etapa

| Control | Resultado de referencia |
|---|---:|
| Fuente MEN | 15.707 filas y 41 columnas |
| Registros nacionales separados | 3 |
| Registros territoriales fuera de 2018–2024 | 7.854 |
| Tabla educativa del periodo | 7.850 filas |
| Llaves duplicadas | 0 |
| Correcciones de población escolar con coma de miles | 1 |
| Correcciones con punto de miles | 845 |
| Poblaciones escolares no utilizables conservadas en original | 80 |
| Coberturas netas pendientes por superar 100 | 984 |
| Deserción ausente | 5 |
| Reprobación ausente | 5 |
| Filas con las tres tasas críticas presentes numéricamente | 7.845 (99,94 %) |
| Filas con las tres tasas críticas utilizables inicialmente | 6.861 (87,40 %) |

**Tener un número no significa que el dato ya pueda usarse.** La utilización conjunta inicial de las tres tasas educativas queda por debajo del 95 % mientras se revisan las 984 coberturas netas. No se declara cumplimiento de Gold ni de las seis variables críticas del panel integrado.

Estas cifras concilian la implementación con el archivo actual; no se usan como constantes para filtrar o forzar el resultado del programa.

## 7. Pruebas y siguiente etapa

Las pruebas de `tests/test_education.py` usan datos sintéticos y archivos temporales. Comprueban conservación de la entrada, encabezados, códigos, nacionales, duplicados, faltantes, separadores de miles, tasas, valores no finitos y reportes serializables.

```powershell
# Ejecutar las comprobaciones educativas desde la raíz del proyecto.
.\venv\Scripts\python.exe -m pytest tests/test_education.py -q
```

Después se implementarán las fuentes de población, DIVIPOLA e internet siguiendo el mismo patrón, y la escritura Silver se añadirá en el punto 4. Las incidencias de educación permanecerán visibles durante ese proceso.
