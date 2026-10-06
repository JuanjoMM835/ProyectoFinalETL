# Etapa 5: integración del panel territorial anual

> Esta página conserva las cifras de la primera publicación del punto 5, con contrato 1.0. El punto 6 revisó cobertura neta con metodología MEN e incorporó evidencia DANE anual. Los resultados vigentes del contrato 1.1 se explican en [etapa_indicadores.md](etapa_indicadores.md).

## 1. Qué se implementó

Esta etapa consume los cuatro archivos Silver ya publicados y construye un panel que conserva **todo el universo educativo MEN de 2018–2024**. Se ejecutó con los datos reales y guardó **7.850 filas y 161 columnas**. Cada fila mantiene la llave `codigo_municipio + anio`.

La implementación completa las uniones y los diagnósticos del punto 5. El resultado se identifica como **exploratorio**: no cumple todavía las metas de aceptación del contrato y los indicadores del punto 6 aún no están calculados.

El flujo implementado es:

```text
4 Parquet Silver + reporte y metadata Silver
              ↓ verificación de integridad, esquema y llaves
Educación → población → internet T4 → catálogo DIVIPOLA
              ↓ coincidencias, faltantes, extras y calidad
Panel integrado exploratorio + reporte + metadata
```

## 2. Responsabilidad de cada archivo

| Archivo | Función |
|---|---|
| `src/extract/read_silver.py` | Lee los cuatro Parquet y los dos JSON Silver. Verifica SHA-256, tamaños, filas, tipos y correspondencia de ejecución y contrato. |
| `src/transform/integrate_sources.py` | Valida las llaves, realiza las uniones izquierdas, conserva procedencia y asigna marcas de coincidencia, ausencia y revisión. |
| `src/transform/quality_integration.py` | Calcula coincidencias, homologación y completitud de las seis variables, siempre sobre todo el universo MEN. |
| `src/load/execution_metadata.py` | Registra la ejecución y vuelve a verificar que las entradas Silver, el código, el contrato y la configuración no cambiaron durante el proceso. |
| `src/load/export_integration.py` | Guarda el panel y sus dos JSON. Relee el Parquet para verificar valores y tipos antes de publicar. |
| `main.py` | Coordina esas funciones mediante `--integrar` y registra el historial en un log independiente. |
| `config/config.yaml` | Define los nombres del panel, reporte, metadata y log de integración, además del contrato que ya gobernaba Silver. |
| `tests/test_integration.py` | Comprueba uniones, cardinalidad, preservación, estados, calidad, lectura de Silver y selección del comando. |
| `tests/test_export_integration.py` | Comprueba publicación, integridad, rutas y recuperación ante fallos de escritura. |
| `tests/test_integration_metadata.py` | Comprueba trazabilidad y detección de cambios de entradas, configuración o código durante la integración. |

Los nuevos módulos contienen comentarios y explicaciones en español. El ejemplo del curso mantiene su papel de referencia; el proceso utiliza la separación entre extracción, transformación, carga y coordinación.

## 3. Cómo se realizan las uniones

### 3.1 Educación determina las filas

La tabla educativa es la base. El programa utiliza su número real de filas, sin escribir `7850` como constante.

Una unión izquierda, `how="left"`, conserva cada fila MEN aunque otra fuente no tenga información. Por ejemplo, si un territorio tiene educación en 2024 pero no un reporte de internet T4 de ese año, sigue existiendo en el panel y sus accesos quedan faltantes.

### 3.2 Población e internet utilizan código y año

Población e internet se unen por `codigo_municipio + anio`. Se exige `validate="one_to_one"`: cada llave solo puede tener una fila en cada fuente. Después de cada unión se verifica que el número, la unicidad y el orden de las llaves MEN se conserven.

Los códigos siguen siendo texto de cinco dígitos. Los nombres no se utilizan para asignar equivalencias. Una fila de Medellín 2024 se une con la misma llave `05001 + 2024`; no puede recibir cifras de 2023 ni datos de un municipio de nombre parecido.

Internet utiliza exclusivamente el T4 preparado en Silver. Si no existe coincidencia, `trimestre_referencia` sigue faltante; no se inventa un trimestre 4 ni se busca T3.

### 3.3 DIVIPOLA utiliza el código

DIVIPOLA es un catálogo sin una fila por año. Se une por `codigo_municipio`, con `validate="many_to_one"`: varias observaciones anuales MEN pueden consultar una única fila del catálogo.

La coincidencia por código se registra en `coincidencia_catalogo_actual`. Los nombres y tipos del catálogo quedan en columnas separadas, como `municipio_catalogo_actual` y `tipo_territorio_catalogo_actual`.

Los nombres de referencia del panel siguen siendo los de educación; `fuente_nombre_territorial="educacion"` hace explícita esa procedencia. No se presentan como nombres históricos acreditados por el catálogo.

## 4. Resultados de la ejecución real

| Fuente consultada | Filas de su Silver | Coincidencias con filas MEN | Filas MEN sin coincidencia | Registros extra fuera de MEN |
|---|---:|---:|---:|---:|
| Población | 7.861 | 7.850 | 0 | 11 territorio–año |
| Internet T4 | 7.815 | 7.813 | 37 | 2 territorio–año |
| DIVIPOLA | 1.122 códigos | 7.848 | 2 | 0 códigos |

El panel conserva **7.850 filas**, con **cero llaves duplicadas**. No se detectaron contradicciones departamentales entre las filas coincidentes.

La coincidencia de internet es **99,53 %**. La del catálogo actual es **99,97 %**; son medidas de coincidencia, no de homologación temporal.

Las dos filas MEN sin catálogo son `94663`, Mapiripana, en 2018 y 2019. Se conservan con sus datos y su código.

Los 11 extras poblacionales corresponden a Nuevo Belén de Bajirá (`27493`, 2018–2023) y Mapiripana (`94663`, 2020–2024). En Silver tienen población cero y revisión territorial pendiente. Los dos extras de internet corresponden a `27086`, 2018 y 2019, con 2 y 4 accesos. No se trasladan esos accesos a `27493`.

Los extras están detallados en el reporte y permanecen en sus Silver; no crean filas nuevas en el universo MEN.

## 5. Qué significan los estados y las columnas auxiliares

- `coincidencia_poblacion`, `coincidencia_internet` y `coincidencia_catalogo_actual`: informan si se encontró la llave correspondiente.
- `estado_poblacion="sin_coincidencia"`: no se encontró una observación poblacional. No ocurrió en esta ejecución, pero la regla está implementada.
- `estado_internet="sin_reporte_t4"`: no existe observación T4 para esa fila MEN. Ocurre en 37 filas.
- `revision_territorial_pendiente`: señala los códigos históricos identificados para revisión.
- `departamento_coincide_*`: compara los códigos departamentales; una ausencia queda desconocida. Los diagnósticos separan contradicciones y metadatos desconocidos.
- `estado_homologacion`, `motivo_homologacion`, `evidencia_homologacion`, `vigencia_desde` y `vigencia_hasta`: permiten identificar y, en una implementación posterior, respaldar la resolución temporal.
- `*_utilizable_fuente`: la variable pasa los controles locales de su fuente.
- `*_utilizable_panel`: además de pasar esos controles, requiere identidad territorial acreditada.

Los campos auxiliares de cada fuente reciben prefijos como `educacion__`, `poblacion__`, `internet__` y `divipola__`. Así se distingue su origen y se evitan columnas ambiguas como `municipio_x` y `municipio_y`.

Una cifra pendiente se conserva. Un subtotal de internet no sustituye un total no utilizable. Los faltantes numéricos siguen siendo faltantes y los ceros observados válidos siguen siendo ceros.

## 6. Por qué la homologación temporal figura en 0 %

El CSV DIVIPOLA disponible **no acredita una vigencia anual para 2018–2024**. El contrato exige evidencia temporal para resolver identidad y correspondencias históricas. Una coincidencia con ese archivo no autoriza a afirmar que la categoría, denominación o territorio representado corresponde a cada año del panel.

Por ello, esta ejecución mantiene las 7.850 filas con `estado_homologacion="pendiente_revision"`; la homologación acreditada es **0 %**. `tipo_territorio="no_resuelto"` indica la limitación temporal, mientras la categoría del catálogo actual permanece disponible por separado.

Esto **no significa que todos los códigos sean incorrectos ni que falten sus cifras**. Significa que todavía no hay una acreditación documentada que permita contarlos como identidades resueltas para una Gold validada.

No se puede habilitar homologación cambiando una bandera global a verdadero. El siguiente trabajo territorial requiere evidencia oficial de vigencia, reglas por código y periodo para los cambios históricos, y comprobaciones de dichas reglas.

## 7. Calidad de las seis variables críticas

Todos los porcentajes siguientes usan **7.850 filas como denominador**, incluyendo faltantes y casos pendientes.

| Variable | Valores numéricos presentes | Utilizables según controles de fuente | Porcentaje de uso local |
|---|---:|---:|---:|
| Población total | 7.850 | 7.833 | 99,78 % |
| Población de centros poblados y rural disperso | 7.850 | 7.833 | 99,78 % |
| Accesos T4 | 7.813 | 7.666 | 97,66 % |
| Cobertura neta | 7.850 | 6.866 | 87,46 % |
| Deserción | 7.845 | 7.845 | 99,94 % |
| Reprobación | 7.845 | 7.845 | 99,94 % |

Las seis variables tienen presencia numérica conjunta en **7.813 filas, 99,53 %**. Pasan conjuntamente los controles locales en **6.702 filas, 85,38 %**. El control conjunto requiere las seis variables de la misma fila; no es el promedio de sus porcentajes.

La diferencia entre presencia y uso local incluye los 984 valores de cobertura neta pendientes de revisión, los cinco faltantes de deserción y reprobación, las revisiones territoriales poblacionales y los accesos pendientes por segmento o territorio.

La aptitud del panel que exige también identidad territorial acreditada es **0 %**, por la limitación temporal descrita. El reporte publica por separado los tres niveles: presencia numérica, uso local y utilización con identidad acreditada.

La aceptación queda `no_cumple`: la meta es 95 % de homologación, 95 % por variable crítica y 95 % conjunto. Aun resolviendo la identidad, la cobertura neta y el conjunto local requieren revisión para alcanzar esa meta. La ejecución del software fue exitosa; el diagnóstico no convierte el resultado en Gold validada.

## 8. Archivos generados y ejecución

Desde la raíz de `ProyectoFinalETL`:

```powershell
# Integrar las cuatro tablas Silver ya publicadas.
.\venv\Scripts\python.exe main.py --integrar

# Verificar todas las etapas implementadas.
.\venv\Scripts\python.exe -m pytest tests -q
```

No se necesita repetir `--silver` para integrar mientras esas entradas sigan siendo las correctas. Si cambian Bronze o las reglas de limpieza, se regenera Silver primero.

Las rutas, relativas a la raíz del proyecto, son:

- `data/gold/panel_integrado_exploratorio.parquet`: panel intermedio, 7.850 × 161.
- `logs/reporte_integracion.json`: coincidencias, extras, faltantes, evidencia y calidad.
- `logs/metadata_integracion.json`: ejecución, origen Silver, versiones, código y hashes.
- `logs/etl_integracion.log`: historial de ejecuciones, incluido cualquier fallo.
- `docs/etapa_integracion.md`: esta explicación.

El panel está en la carpeta Gold porque es un resultado integrado, y su nombre y metadata explicitan que es intermedio y exploratorio. `indicadores_municipio_anio.parquet` y `indicadores_municipio_anio.csv` siguen reservados para el punto 6.

La escritura utiliza archivos temporales, relee el Parquet y verifica valores y tipos antes de publicar. La metadata se publica al final; ante un fallo de publicación se restauran las salidas anteriores. Los cuatro Silver y los dos JSON Silver conservaron sus hashes después de esta ejecución.

## 9. Cómo continuamos

La base técnica del punto 5 está implementada, probada y ejecutada. Las excepciones de datos quedan visibles para resolverlas con evidencia.

El punto 6 implementará accesos por 100 habitantes, porcentaje de centros poblados y rural disperso, y crecimiento anual de accesos. Cada indicador necesitará sus propias condiciones de cálculo y motivos de ausencia: denominador positivo, valores utilizables y, para crecimiento, año anterior consecutivo y accesos anteriores positivos.

Antes de presentar una Gold validada habrá que documentar la identidad temporal y tratar los valores pendientes. La velocidad ponderada, participación de fibra y el índice continúan sujetos a las verificaciones y metodología definidas en el contrato.
