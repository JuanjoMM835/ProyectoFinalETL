# Contrato de datos del proyecto ETL

- **Proyecto:** ProyectoFinalETL.
- **Versión del contrato:** 1.0.
- **Fecha:** 2026-10-05.
- **Estado:** propuestas aceptadas para la primera versión del ETL.
- **Alcance de este documento:** definir datos, transformaciones, validaciones y entregables antes de implementar el pipeline. La existencia de este contrato no implica que Silver, Gold o el ETL estén implementados.

## 1. Propósito

Construir una tabla territorial anual de Colombia para el periodo 2018–2024, integrando educación, población e internet fijo. La tabla permitirá comparar indicadores y servirá como base para un índice de prioridad digital y educativa y un tablero posteriores.

El análisis identificará asociaciones y patrones territoriales. No demostrará, por sí solo, que la falta de internet cause deserción u otros resultados educativos.

## 2. Universo, periodo y granularidad

### 2.1 Universo de la primera versión

La fuente educativa del Ministerio de Educación Nacional (MEN) determina las filas de la tabla integrada:

1. Seleccionar los registros territoriales del MEN de 2018 a 2024, inclusive.
2. Separar los registros de nivel nacional mediante una regla documentada sobre su código y una comprobación de su identificación en la fuente.
3. Conservar municipios y áreas no municipalizadas presentes en ese universo. Identificar su categoría en `tipo_territorio` cuando exista evidencia.
4. No excluir una fila porque no encuentre internet, población o coincidencia en DIVIPOLA. Conservarla con sus faltantes y estados de calidad.
5. Mantener los códigos históricos sin resolver con su código original y evidencia; no inventar una homologación.

El universo no equivale automáticamente a todos los territorios del catálogo DANE ni a todos los registros de la fuente de internet. Se reportarán territorios presentes en otras fuentes pero ausentes en la base educativa.

Los 7.850 registros observados en la exploración son una referencia de conciliación, no una constante que se escribirá en el programa. Si el conjunto de entrada cambia, se recalculará y explicará el universo.

### 2.2 Periodo

- Periodo principal: **2018–2024**.
- Los registros fuera del periodo permanecen en Bronze, pero no forman parte de las salidas analíticas iniciales.
- La fuente de población contiene proyecciones hasta 2042; solo se seleccionarán los años del proyecto.
- La inclusión de 2017 para calcular el crecimiento de 2018 requeriría una ampliación explícita de los datos auxiliares del cálculo. No está incluida en esta primera versión.

### 2.3 Unidad de observación y llave

Cada fila de Gold representa **un territorio en un año**.

```text
llave = codigo_municipio + anio
```

La llave debe estar completa y ser única. Se conserva el nombre `codigo_municipio` para mantener consistencia con las fuentes y los notebooks, aunque el universo también contiene áreas no municipalizadas.

- `codigo_municipio`: texto de cinco dígitos; conserva ceros iniciales.
- `codigo_departamento`: texto de dos dígitos.
- `anio`: entero entre 2018 y 2024.

No se permitirá que una unión multiplique las filas por llaves repetidas. Una llave incompleta o duplicada impide publicar Gold como resultado válido y debe investigarse antes de continuar.

## 3. Fuentes y capa Bronze

Las rutas de esta sección son relativas a la raíz de `ProyectoFinalETL`.

| Fuente | Archivo original en `data/bronze/` | Contenido y lectura |
|---|---|---|
| Educación, MEN | `MEN_ESTADISTICAS_EN_EDUCACION_EN_PREESCOLAR__B_SICA_Y_MEDIA_POR_MUNICIPIO.csv` | CSV separado por coma, lectura UTF-8 con tratamiento de BOM; indicadores educativos anuales. |
| Internet fijo, CRC | `ACCESOS_INTERNET_FIJO_2_8.csv` | CSV separado por punto y coma, UTF-8; lectura por bloques; accesos por trimestre y categorías de reporte. |
| Población, DANE | `PPED-AreaMun-2018-2042_VP.xlsx` | Hoja `PobMunicipalxÁrea`, encabezado identificado en la fila utilizada por el notebook (`header=7`); separar notas de los datos. |
| Catálogo territorial, DIVIPOLA | `DIVIPOLA-_C_digos_municipios.csv` | CSV separado por coma, lectura UTF-8 con tratamiento de BOM; códigos, nombres y tipo territorial. |

Antes de procesar se comprobará la existencia del archivo, sus columnas necesarias y, para Excel, la hoja y el encabezado. Un cambio de estructura se reportará como error de entrada.

Los archivos Bronze son originales y no se modificarán ni sobrescribirán con valores limpios. Esta primera versión utiliza los originales ya disponibles en Bronze; no exige duplicarlos en `data/source/` ni automatizar su descarga.

Se registrarán la versión y fecha de actualización de cada fuente cuando estén disponibles. Las fechas de descarga desconocidas se marcarán como desconocidas; no se inventarán.

## 4. Capas y salidas comprometidas

| Capa | Responsabilidad | Salidas iniciales |
|---|---|---|
| Bronze | Conservar los originales y su procedencia. | Los cuatro archivos de entrada. |
| Silver | Normalizar, depurar y validar cada fuente de manera independiente. | `educacion_limpia.parquet`, `poblacion_limpia.parquet`, `internet_municipio_anio.parquet`, `divipola_limpia.parquet`. |
| Gold | Integrar el universo educativo y calcular indicadores utilizables. | `indicadores_municipio_anio.parquet` y su copia `indicadores_municipio_anio.csv`. |
| Evidencia de ejecución | Explicar el procesamiento, controles y excepciones. | `logs/etl_pipeline.log`, `logs/reporte_calidad.json` y `logs/metadata_ejecucion.json`. |

Silver se guardará en `data/silver/` y Gold en `data/gold/`. La exportación CSV conservará los códigos con ceros iniciales; sus consumidores deberán leerlos como texto. Parquet será el formato principal para conservar tipos.

La primera Gold puede existir antes de implementar el índice. Los campos del índice no se presentarán como calculados hasta aprobar e implementar su metodología.

## 5. Diccionario del núcleo de Gold

Los campos de la llave son obligatorios y no admiten faltantes. Las demás columnas deben existir en el esquema, pero pueden contener faltantes explícitos, sujetos a los controles de calidad.

| Columna | Tipo lógico | Definición y unidad | Regla principal |
|---|---|---|---|
| `codigo_municipio` | Texto | Código territorial de cinco dígitos. | No vacío; componente de la llave. |
| `anio` | Entero | Año de referencia. | 2018–2024; componente de la llave. |
| `codigo_departamento` | Texto | Código de departamento de dos dígitos. | Contrastar con la identidad territorial y el prefijo del código cuando corresponda. |
| `municipio` | Texto | Nombre territorial oficial cuando esté homologado. | Conservar por separado el nombre original para trazabilidad. |
| `departamento` | Texto | Nombre del departamento. | No homologar solo por similitud de nombres. |
| `tipo_territorio` | Texto | Municipio, área no municipalizada, isla u otra categoría sustentada por el catálogo. | Si no se resuelve, utilizar categoría explícita `no_resuelto`. |
| `poblacion_total` | Entero anulable | Personas según la serie DANE utilizada. | No negativa; denominador positivo para indicadores por habitante. |
| `poblacion_cabecera` | Entero anulable | Personas residentes en cabecera. | No negativa y consistente con el total. |
| `poblacion_centros_rural` | Entero anulable | Personas en centros poblados y rural disperso. | No negativa y consistente con el total. |
| `accesos_t4` | Entero anulable | Accesos de internet fijo del cuarto trimestre. | No negativos; ausencia de reporte no equivale a cero. |
| `cobertura_neta` | Decimal anulable | Indicador del MEN expresado en porcentaje. | Mantener definición y escala de la fuente; revisar extremos. |
| `desercion` | Decimal anulable | Indicador de deserción del MEN, en porcentaje. | Mantener definición y escala; revisar valores incompatibles con ella. |
| `reprobacion` | Decimal anulable | Indicador de reprobación del MEN, en porcentaje. | Mantener definición y escala; revisar valores incompatibles con ella. |
| `accesos_por_100_habitantes` | Decimal anulable | Accesos T4 / población total × 100. | Requiere accesos utilizables y población positiva. |
| `porcentaje_centros_rural` | Decimal anulable | Población de centros poblados/rural disperso / población total × 100. | Requiere componentes utilizables y población positiva. |
| `crecimiento_anual_accesos` | Decimal anulable | Variación porcentual frente al año inmediatamente anterior. | Año anterior consecutivo, datos utilizables y accesos anteriores positivos. |
| `trimestre_referencia` | Entero anulable | Trimestre de la observación anual de internet. | 4 cuando existe el dato utilizado; faltante si no existe observación. |
| `estado_homologacion` | Texto | Resultado de la validación territorial. | `resuelto_catalogo`, `resuelto_regla_historica` o `pendiente_revision`. |
| `estado_poblacion` | Texto | Disponibilidad y validez de la población. | `disponible`, `sin_coincidencia`, `no_utilizable` o `pendiente_revision`. |
| `estado_internet` | Texto | Disponibilidad y validez del dato anual. | `disponible`, `sin_reporte_t4`, `no_utilizable` o `pendiente_revision`. |

Silver puede conservar más campos que este núcleo, incluidos indicadores educativos por nivel, categorías de internet, valores originales relevantes y marcas de calidad. Una conversión o agregación debe poder relacionarse con su fuente.

## 6. Reglas de transformación

### 6.1 Códigos y nombres

- Leer los códigos como texto y quitar espacios exteriores.
- Completar con ceros iniciales únicamente valores formados por dígitos y con longitud compatible; no usar el relleno para ocultar formatos inválidos.
- No tratar un código nacional formado por ceros como un municipio.
- Validar pertenencia al catálogo y consistencia del departamento.
- Priorizar los códigos para las uniones. Los nombres se usan para consulta y revisión, no como llave automática.
- Conservar el código original junto con cualquier código homologado y la regla aplicada.
- Un catálogo actual no resuelve automáticamente la geografía histórica. Las correspondencias históricas necesitan evidencia de su validez temporal.
- Una bandera `pendiente_revision` no cuenta como homologación resuelta.

### 6.2 Educación

- Normalizar nombres de columnas y documentar su correspondencia con la fuente.
- Reconocer campos vacíos sin alterar valores legítimos.
- Convertir números con reglas por campo. El caso `1,174,274` de población escolar requiere reconocer separadores de miles; no aplicar un reemplazo universal de comas.
- Separar el nivel nacional y seleccionar 2018–2024.
- Conservar la escala porcentual del MEN: `5.2` representa 5,2 %, no una proporción de 0,052.
- Revisar valores extremos sin borrarlos ni limitarlos automáticamente. Una cobertura bruta superior a 100 puede ser conceptualmente válida; no se usará un límite universal de 100 para todos los indicadores.
- La columna `SEDES_CONECTADAS_A_INTERNET` carece de datos en todo el periodo revisado. Se conservará su limitación y no se imputará cero ni se ofrecerá como indicador calculable con esta fuente.

### 6.3 Población

- Separar notas y pies de archivo de las filas de datos, conservando su información de procedencia.
- Utilizar la población de la misma serie, territorio y año para total y componentes.
- Transformar las categorías de área en columnas: total, cabecera y centros poblados/rural disperso.
- Comprobar unicidad de territorio–año–área antes de transformar.
- Comprobar la igualdad `poblacion_total = poblacion_cabecera + poblacion_centros_rural`.
- Comprobar `0 ≤ poblacion_centros_rural ≤ poblacion_total`. La categoría de centros poblados y rural disperso ya es un agregado de la fuente; no sumar nuevamente componentes que dupliquen ese agregado.
- Conservar ceros observados y distinguirlos de faltantes. No dividir por población cero.
- Identificar cambios territoriales y series históricas que requieren revisión, incluidos los casos detectados de Nuevo Belén de Bajirá, Riosucio, Barrancominas y Mapiripana. No transferir población entre códigos sin una regla respaldada.
- Identificar el denominador como población de la serie DANE utilizada; no presentarlo automáticamente como un conteo observado.

### 6.4 Internet y referencia anual

- Leer por bloques y conservar controles globales. No perder registros o duplicados entre bloques.
- Convertir accesos a enteros no negativos y velocidades con el tratamiento decimal correspondiente.
- Separar registros nacionales y códigos territoriales no resueltos.
- Seleccionar 2018–2024 y trimestre 4.
- Agregar accesos dentro de territorio–año, comprobando que las categorías sumadas no son totales superpuestos o repeticiones del mismo reporte.
- No sumar los cuatro trimestres como si representaran conexiones nuevas.
- Si falta T4, conservar faltante y `estado_internet = sin_reporte_t4`. No usar T3 u otro trimestre como sustitución automática.
- El literal `NA` observado en tecnología no se interpretará automáticamente como campo vacío; se verificará su significado antes de clasificarlo.
- Los registros de internet sin población o fuera del universo educativo se conservarán como evidencia de conciliación aunque no creen filas nuevas en Gold.

### 6.5 Integración

- Educación con población: unión por `codigo_municipio` y `anio`, conservando todas las filas del universo educativo.
- Resultado con internet anual: misma llave y conservación del universo educativo.
- Resultado con catálogo territorial: por código; aplicar reglas históricas temporales solo cuando estén documentadas.
- Validar las cardinalidades antes y durante cada unión.
- El número de filas de Gold debe ser igual al del universo educativo válido para la llave; no disminuir por falta de datos ni aumentar por una unión incorrecta.
- Ante una llave duplicada o incompleta, detener la publicación válida de Gold y emitir el diagnóstico. No eliminar duplicados silenciosamente.

## 7. Faltantes, ceros y valores en revisión

| Caso | Tratamiento |
|---|---|
| Campo vacío o dato no disponible | Faltante explícito, nunca cero inventado. |
| Cero reportado y válido | Conservar cero con su origen. |
| Falta internet T4 | Conservar fila y marcar ausencia de observación. |
| Población total cero | Conservar valor; indicador por habitante o ruralidad queda faltante con motivo de denominador inválido. |
| Número no convertible | Conservar evidencia original y motivo; no utilizarlo en cálculos hasta resolverlo. |
| Valor extremo | Marcar para revisión; resolver con la definición y documentación de la fuente. |
| Código histórico sin homologación | Conservar registro y evidencia; no asignar otro código por semejanza del nombre. |
| Dato educativo inválido o pendiente | Conservar el valor original; excluirlo del cálculo que exija validez hasta resolverlo, sin borrar la fila. |

Los indicadores no calculables deben acompañarse de un motivo en el reporte de calidad o una marca por fila. No clasificar un territorio como prioridad baja simplemente porque falten datos.

## 8. Indicadores y condiciones de cálculo

### 8.1 Indicadores de la primera Gold

```text
accesos_por_100_habitantes = accesos_t4 / poblacion_total × 100

porcentaje_centros_rural = poblacion_centros_rural / poblacion_total × 100

crecimiento_anual_accesos =
    (accesos_t4_actual - accesos_t4_anterior) / accesos_t4_anterior × 100
```

- Accesos por 100 habitantes expresa conexiones respecto a población, no porcentaje de personas conectadas.
- Para población se requiere denominador positivo y datos utilizables.
- Para crecimiento se requiere el año inmediatamente anterior, sin saltar años faltantes, y accesos anteriores positivos.
- En 2018 el crecimiento no aplica en el alcance inicial porque no incluye 2017 como dato auxiliar. Los demás años se evaluarán sin convertir ausencias o denominadores cero en crecimiento cero.
- Cobertura neta, deserción y reprobación son indicadores suministrados por el MEN, no tasas que se reconstruyan sin sus denominadores.
- Los cálculos conservarán precisión suficiente; el redondeo de presentación no cambiará las validaciones ni la clasificación futura.

### 8.2 Indicadores sujetos a verificación

La velocidad ponderada y la participación de fibra se añadirán después de confirmar:

1. Unidad y significado de las velocidades reportadas y conversiones necesarias.
2. Correspondencia entre códigos/nombres de tecnología y la categoría fibra.
3. Significado de tecnologías desconocidas o `NA`.
4. Granularidad que permita agregar sin doble conteo.
5. Tratamiento de velocidades cero, faltantes o no utilizables y cobertura de accesos representados en el promedio.

Para velocidad se acumularán numerador y denominador compatibles con observaciones válidas; no se promediarán los promedios de los bloques. Para fibra se documentará el denominador y se reportará la participación de tecnología desconocida.

Estas verificaciones están pendientes. El contrato no fija una unidad de velocidad ni una lista de tecnologías sin evidencia.

### 8.3 Índice y tablero posteriores

El índice corresponde al punto 7 del plan de implementación. Antes de calcularlo se definirán variables, orientación, normalización, pesos, faltantes y límites de clasificación baja/media/alta.

Se decidirá si la prioridad es relativa dentro de cada año o comparable entre años. Ruralidad no se interpretará automáticamente como mal desempeño. El tablero y las agregaciones departamentales se implementarán después; no se asumirán tasas departamentales válidas a partir del promedio simple de porcentajes municipales.

## 9. Criterios de calidad y aceptación

### 9.1 Invariantes estructurales

- Llave completa y única: **100 %**.
- Periodo, tipos y columnas obligatorias: **100 %** de conformidad.
- Ninguna multiplicación de filas por uniones.
- Población y accesos utilizados en cálculos deben cumplir sus restricciones de contenido.
- Verificar componentes poblacionales sin imputar un total ausente.

La detección de una inconsistencia no autoriza a corregir o borrar silenciosamente la fuente. Se conservará el registro y se registrará el tratamiento.

### 9.2 Homologación territorial

```text
homologacion_panel =
    filas territorio–año con identidad territorial resuelta
    / todas las filas del universo educativo seleccionado × 100
```

Meta: **al menos 95 %**. Se cuentan solo identidades sustentadas por catálogo o regla histórica respaldada, no banderas de revisión.

Reportar adicionalmente códigos distintos resueltos y pendientes, y separar las categorías territoriales cuando se conozcan. El indicador mide el panel educativo, no todo el catálogo ni todos los registros crudos de CRC.

### 9.3 Completitud crítica

Variables críticas iniciales:

- `poblacion_total`.
- `poblacion_centros_rural`.
- `accesos_t4`.
- `cobertura_neta`.
- `desercion`.
- `reprobacion`.

```text
completitud_variable =
    valores presentes, convertibles y semánticamente utilizables
    / filas elegibles según la definición de la variable × 100

completitud_conjunta =
    filas con todas las variables críticas utilizables
    / filas elegibles para el conjunto crítico × 100
```

En estas seis variables el denominador inicial es el universo territorial educativo completo. Una ausencia de fuente, un código no resuelto o un dato no utilizable no justifican quitar la fila del denominador. Cualquier cambio de elegibilidad exige justificarlo y versionar el contrato.

Meta operativa: **al menos 95 % por variable y al menos 95 % de completitud conjunta**. El criterio conjunto es una decisión de calidad adoptada para la implementación; no se afirma que la exploración ya lo haya demostrado.

La presencia de un cero válido cuenta para completitud del dato observado. Un cero de población o de accesos anteriores puede impedir un indicador derivado; se reportará por separado su calculabilidad.

Las verificaciones orientativas de extremos no invalidarán automáticamente todos los valores superiores a 100. La utilización semántica se resolverá según el indicador y la evidencia; los casos pendientes se identificarán como tales.

No son críticas en esta versión: sedes conectadas, crecimiento 2018, indicadores de velocidad/fibra pendientes y el índice aún no definido. La calculabilidad del crecimiento de 2019–2024 se reportará aparte, incluyendo faltantes y denominadores cero.

### 9.4 Disponibilidad de internet

```text
coincidencia_internet_t4 =
    filas del universo educativo con observación correspondiente de internet T4
    / todas las filas del universo educativo seleccionado × 100
```

No confundir esta medida con homologación ni con completitud semántica. Una coincidencia puede existir y contener un dato no utilizable.

### 9.5 Publicación de resultados

Los errores de entrada o de llave detienen la etapa afectada. Los casos faltantes o históricos se conservan y reportan. Si no se alcanzan las metas de aceptación, se emite diagnóstico y el resultado no se presenta como Gold validada.

Es posible conservar una salida exploratoria identificada como tal para resolver problemas. No se sustituirán datos ni reducirán denominadores para declarar cumplimiento artificial.

## 10. Reporte y trazabilidad

Cada ejecución registrará:

- Fecha de ejecución y versión del contrato y del código disponible.
- Archivos de entrada, tamaño y huella de integridad cuando sea posible.
- Fecha/versión de la fuente cuando se conozca y fecha de descarga real si está documentada.
- Periodo, universo y referencia T4 utilizados.
- Filas leídas, separadas, seleccionadas, agregadas y exportadas por fuente.
- Llaves incompletas, duplicadas y códigos pendientes.
- Coincidencias y diferencias entre fuentes, incluido lo que queda fuera de Gold.
- Completitud por variable y conjunta, con numeradores y denominadores.
- Calculabilidad de indicadores y motivos de ausencia.
- Reglas históricas, correcciones explícitas y decisiones de revisión aplicadas.
- Rutas de las salidas y estado final: validado, exploratorio o fallido.

Las reglas de transformación deben ser deterministas: con los mismos archivos y configuración deben producir los mismos datos. Las fechas de ejecución en los metadatos pueden cambiar.

## 11. Referencias exploratorias para conciliar la implementación

Las cifras siguientes provienen de la revisión previa y la reejecución exploratoria del notebook de población. No son valores fijos de aceptación ni verificaciones nuevas realizadas al redactar este contrato.

| Control | Referencia observada |
|---|---:|
| Universo educativo territorial 2018–2024 | 7.850 filas |
| Filas con población correspondiente | 7.850 |
| Filas con internet T4 correspondiente | 7.813 |
| Filas sin coincidencia de internet T4 | 37 |
| Coincidencia de internet T4 | 99,53 % |
| Llaves territorio–año duplicadas en el cruce | 0 |
| Faltantes numéricos de cobertura neta | 0 |
| Faltantes numéricos de deserción | 5 |
| Faltantes numéricos de reprobación | 5 |
| Faltantes de sedes conectadas en el periodo | 7.850 |

La completitud numérica exploratoria no resuelve automáticamente la validez semántica de extremos ni demuestra la completitud conjunta de todas las variables críticas.

Como comprobación de conciliación, Medellín 2024 (`05001`) presentó población total de 2.524.747, 791.436 accesos T4 y 31,35 accesos por 100 habitantes en la presentación redondeada.

## 12. Responsabilidades de implementación y decisiones pendientes

| Componente | Responsabilidad posterior |
|---|---|
| `config/config.yaml` | Declarar fuentes, rutas, periodo, T4, salidas y umbrales definidos por este contrato. |
| `requirements.txt` | Declarar dependencias compatibles para lectura, Parquet, configuración y comprobaciones. |
| `src/extract/` | Leer y validar la estructura de las fuentes sin modificar Bronze. |
| `src/transform/` | Aplicar limpieza, validaciones, integración e indicadores según el contrato. |
| `src/load/export_results.py` | Persistir tablas y evidencias, sin recalcular ni volver a limpiar datos. |
| `main.py` | Coordinar las etapas, fallos y registro de ejecución. |
| `tests/` | Comprobar reglas relevantes de llaves, uniones, faltantes, ceros y cálculos. |
| `notebooks/` | Conservar exploración y contrastar resultados; después analizar Gold. |
| `README.md` | Explicar preparación del entorno, ejecución, resultados y limitaciones, enlazando este contrato. |

Pendientes antes de incorporar velocidad y fibra: verificar unidades, significado de categorías y agregación válida. Pendientes durante la limpieza: resolver o conservar con evidencia las excepciones territoriales y valores extremos. Pendiente para el punto 7: aprobar la metodología del índice.

Documentar estas verificaciones pendientes no impide implementar el núcleo inicial. No se presentarán los indicadores diferidos como ya definidos o calculados.

## 13. Control de cambios

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-10-05 | Primera documentación de las propuestas aceptadas: universo MEN territorial, periodo 2018–2024, llave, T4, capas, diccionario, excepciones, calidad y salidas. |

Los cambios de universo, periodo, llaves, unidades, elegibilidad, referencia temporal o metodología de indicadores deben registrarse en una nueva versión y reflejarse en configuración y metadatos de ejecución.
