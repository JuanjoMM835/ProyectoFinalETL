# Extracción y limpieza del catálogo DIVIPOLA

Fecha: 2026-10-05. Esta etapa implementa el tercer componente del punto 3. La fuente es `data/bronze/DIVIPOLA-_C_digos_municipios.csv`, conservada sin modificaciones.

## 1. Qué aporta este dataset

Educación y población tienen una fila por territorio y año después de su preparación. DIVIPOLA tiene una fila por código territorial y permite consultar su nombre, departamento y categoría en el archivo disponible.

| Fuente preparada | Llave |
|---|---|
| Educación | `codigo_municipio + anio` |
| Población | `codigo_municipio + anio` |
| DIVIPOLA | `codigo_municipio` |

El nombre `codigo_municipio` se mantiene para compatibilidad con las fuentes, aunque también identifica áreas no municipalizadas y una isla. El catálogo no recibe una columna `anio` inventada ni se replica siete veces.

**El CSV no documenta fecha de corte ni vigencia histórica.** Su coincidencia con un código de 2018–2024 no acredita por sí sola que el nombre, categoría o límites actuales describan ese año. La homologación del panel y las reglas históricas se implementarán durante la integración.

## 2. Responsabilidad de los archivos

### `src/extract/extract_divipola.py`

La función `extraer_divipola(configuracion_fuente, raiz_proyecto)`:

1. Obtiene ruta, separador, codificación y opciones desde `sources.divipola` del YAML.
2. Comprueba que existe el archivo y que se declaró una fuente CSV.
3. Verifica el encabezado original y las columnas obligatorias antes de pandas, para detectar repeticiones sin que un renombrado automático las oculte.
4. Lee todo el archivo como texto; no filtra ni cambia valores.
5. Guarda archivo y opciones de lectura en `datos.attrs["origen_csv"]`. Las fechas desconocidas permanecen desconocidas y `vigencia_historica_verificada` es falsa.
6. Devuelve el DataFrame original en memoria.

### `src/transform/clean_divipola.py`

La función `limpiar_divipola(datos_originales, configuracion)` devuelve `(catalogo, reporte)`.

Su secuencia es:

1. Trabajar sobre una copia y comprobar las cinco columnas territoriales obligatorias.
2. Normalizar encabezados, sin permitir colisiones o sobrescribir columnas reservadas.
3. Guardar originales y `registro_origen` antes de transformar valores. El ordinal identifica el registro CSV, no una línea física.
4. Quitar espacios externos y conservar faltantes.
5. Normalizar códigos válidos a cinco y dos dígitos, conservando texto. Un cero nacional o un texto mal formado no se convierte en un municipio.
6. Detenerse si el código municipal está incompleto, es inválido o queda repetido tras normalizar.
7. Reconocer tipos territoriales y conservar categorías desconocidas como `no_resuelto`, con su original.
8. Revisar prefijo departamental, metadatos incompletos y nombres departamentales contradictorios para un mismo código.
9. Convertir coordenadas disponibles con una regla específica de decimales y rango.
10. Añadir estados y devolver un reporte de controles del catálogo.

Una columna nueva se conserva como texto bajo un encabezado normalizado y se informa en `columnas_nuevas_no_tipificadas`; no se le asigna una interpretación numérica sin evidencia.

### `main.py`

`ejecutar_divipola()` lee la configuración compartida, llama al extractor y al transformador y devuelve la tabla y el reporte. El comando `--fuente divipola` muestra los controles del catálogo. Los comandos anteriores de educación y población siguen disponibles; sin `--fuente` se prepara educación.

La coordinación conserva el patrón utilizado en el ejemplo `proyecto_final_2026`: funciones de extracción y transformación llamadas desde `main.py`. Las reglas se adaptan al contrato territorial y no eliminan filas ni imputan faltantes para aparentar un catálogo completo.

## 3. Correspondencia de columnas y tipos

| Encabezado original | Columna preparada | Tipo |
|---|---|---|
| `Código Municipio` | `codigo_municipio` | `string` de cinco dígitos |
| `Nombre Municipio` | `municipio` | `string` |
| `Código Departamento` | `codigo_departamento` | `string` de dos dígitos |
| `Nombre Departamento` | `departamento` | `string` |
| `Tipo: Municipio / Isla / Área no municipalizada` | `tipo_territorio` | `string` con categorías explícitas |
| `longitud` | `longitud` | `Float64` anulable, si existe en la fuente |
| `Latitud` | `latitud` | `Float64` anulable, si existe en la fuente |

Los nombres mantienen sus tildes y la escritura de la fuente, salvo espacios externos. Solo se utiliza una forma sin tildes ni diferencias de mayúsculas para comparar etiquetas de tipo y coherencia de nombres departamentales; esa comparación no sobrescribe los nombres.

Ejemplos de transformación:

| Campo | Entrada | Salida |
|---|---|---|
| Código municipal | `5001` | `05001`, como texto |
| Código departamental | `5` | `05`, como texto |
| Tipo | `Municipio` | `municipio` |
| Tipo | `Área no municipalizada` | `area_no_municipalizada` |
| Tipo | `Isla` | `isla` |
| Tipo desconocido o vacío | Original conservado | `no_resuelto` |
| Longitud | `-75,581775` | `-75.581775`, como decimal |

La coma decimal se interpreta únicamente en longitud y latitud. Se comprueban los rangos globales longitud −180 a 180 y latitud −90 a 90. El cero observado es válido. Un texto inválido, infinito o fuera de rango queda faltante en el campo limpio, con original y estado preservados; no se recorta al límite.

Las coordenadas son auxiliares para ubicación. No son la llave de una unión, no representan una geometría de límites y no resuelven cambios históricos. Si las columnas no existen, no se inventan coordenadas.

## 4. Controles y estados

| Campo | Significado |
|---|---|
| `departamento_inconsistente` | Falta un código departamental válido o no coincide con el prefijo del código municipal. |
| `metadatos_incompletos` | Falta código departamental o nombre territorial/departamental. |
| `departamento_nombre_inconsistente` | El mismo código departamental tiene nombres contradictorios, descartando diferencias de escritura. |
| `tipo_no_resuelto` | La categoría original está vacía o no tiene una regla reconocida. |
| `estado_catalogo = disponible` | El registro supera los controles territoriales iniciales del catálogo disponible. |
| `estado_catalogo = pendiente_revision` | Existe una incidencia territorial o de metadatos que debe revisarse. |
| `estado_longitud` / `estado_latitud` | Disponible, faltante, no numérico o no utilizable; se crean para coordenadas presentes. |
| `coordenadas_utilizables` | Ambas coordenadas existen y superan sus controles. |

Una coordenada no utilizable no invalida automáticamente los códigos y categorías. Por eso `estado_catalogo` y `coordenadas_utilizables` son comprobaciones separadas.

**`estado_catalogo` no equivale a `estado_homologacion`.** Esta etapa no modifica las marcas de educación o población. No declara resueltos los cuatro casos históricos del contrato: Nuevo Belén de Bajirá, Riosucio, Barrancominas y Mapiripana.

## 5. Resultado y contraste con otras fuentes

| Control del CSV actual | Resultado |
|---|---:|
| Filas originales y preparadas | 1.122 |
| Columnas originales | 7 |
| Códigos departamentales distintos | 33 |
| Municipios según la categoría del archivo | 1.103 |
| Áreas no municipalizadas | 18 |
| Isla según la categoría del archivo | 1 |
| Códigos duplicados | 0 |
| Departamentos inconsistentes | 0 |
| Metadatos incompletos o categorías no resueltas | 0 |
| Registros disponibles en el catálogo | 1.122 |
| Pares de coordenadas utilizables | 1.122 |

El archivo clasifica a San Andrés (`88001`) como `Isla`; se conserva esa etiqueta sin redefinirla como municipio. El CSV no contiene Mapiripana (`94663`).

Los diagnósticos por código, sin modificar las tablas independientes, dan:

| Fuente | Filas | Coinciden con catálogo | Sin coincidencia | Departamento discrepante en coincidencias |
|---|---:|---:|---:|---:|
| Educación | 7.850 | 7.848 | 2 | 0 |
| Población | 7.861 | 7.854 | 7 | 0 |

Los registros sin coincidencia son Mapiripana: educación 2018–2019 y población 2018–2024. Permanecen en sus fuentes con los controles ya definidos. No se eliminan ni se sustituyen por Barrancominas.

Nuevo Belén de Bajirá, Riosucio y Barrancominas sí aparecen en el catálogo, pero esa coincidencia no resuelve su geografía histórica. No se calcula ni declara aquí un porcentaje de homologación temporal.

Los nombres presentan variantes como Cali/Santiago de Cali, Cúcuta/San José de Cúcuta y Barranco Minas/Barrancominas. Por eso se priorizan códigos y se conservan los rótulos originales; no se aplica una unión automática por semejanza de nombres.

La conciliación reproduce la selección de códigos y el cruce izquierdo `many_to_one` de la celda 8 del notebook `analisis_poblacion.ipynb`. Cada catálogo único puede corresponder a varias filas anuales, sin multiplicar el panel. El diagnóstico es una comprobación, no una Gold publicada.

## 6. Cómo ejecutar y consultar

Desde la raíz de `ProyectoFinalETL`, en PowerShell:

```powershell
# Preparar el catálogo y mostrar sus controles.
.\venv\Scripts\python.exe main.py --fuente divipola

# Verificar las tres fuentes implementadas.
.\venv\Scripts\python.exe -m pytest tests/test_education.py tests/test_population.py tests/test_divipola.py -q
```

En un notebook abierto en la raíz del proyecto:

```python
# Importar no ejecuta automáticamente las etapas.
from main import ejecutar_divipola

# Obtener el catálogo y su evidencia de controles.
catalogo, reporte = ejecutar_divipola()

# Consultar códigos, categorías y estados.
display(catalogo.head())
print(reporte["tipos_territorio"])
print(reporte["estados_catalogo"])
```

Las rutas se resuelven desde el proyecto y no dependen de una ruta personal escrita en el extractor. Se puede ejecutar `main.py` por ruta absoluta desde otra carpeta.

El resultado permanece en memoria. La escritura `data/silver/divipola_limpia.parquet`, los reportes persistentes y el log se añadirán con el punto 4. La integración y la comprobación del panel corresponderán a una etapa posterior.

## 7. Verificación y siguiente componente

`tests/test_divipola.py` utiliza datos sintéticos y archivos temporales. Comprueba conservación de la fuente y la entrada, encabezados, códigos, duplicados, tipos, metadatos, coordenadas, campos opcionales, trazabilidad y JSON estricto. Verifica también que no se inventen años ni homologación histórica.

La fuente real se contrasta por separado contra el CSV y el notebook, conservando su huella SHA-256. Las pruebas de software no acreditan por sí solas la vigencia histórica del catálogo.

La verificación final pasó 35 casos DIVIPOLA, 38 de población y 31 de educación: 104 pruebas en conjunto. También se ejecutó correctamente `main.py --fuente divipola` contra el CSV real.

Tenemos implementadas extracción y limpieza independientes de educación, población y DIVIPOLA. El siguiente componente del punto 3 es internet fijo: lectura por bloques, validación de categorías y accesos, selección de T4 y agregación anual sin doble conteo. Después se guardará Silver y se integrará Gold según el contrato.
