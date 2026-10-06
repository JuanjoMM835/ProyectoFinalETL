# Comprobaciones del proyecto

Las primeras comprobaciones están en `test_education.py`. Usan datos sintéticos y archivos temporales para verificar reglas que podrían perder o interpretar mal los datos. No modifican las fuentes Bronze.

Desde la raíz de `ProyectoFinalETL`, ejecutar:

```powershell
# Usar pytest instalado en el entorno virtual del proyecto.
.\venv\Scripts\python.exe -m pytest tests/test_education.py -q
```

Se comprueban encabezados obligatorios y repetidos, conservación de la entrada, separación de nacionales, el municipio Colombia de Huila, normalización de códigos, llaves duplicadas, años inválidos, faltantes, miles en población, tasas y serialización del reporte.

La conciliación con los datos reales se realiza por separado, comparando las columnas de la fuente con el notebook educativo y explicando las diferencias deliberadas de población escolar. Los valores superiores a 100 de cobertura neta quedan pendientes de revisión; pasar las pruebas de software no demuestra por sí solo la calidad semántica de toda la fuente.

## Población DANE

Desde la raíz del proyecto, ejecutar también las comprobaciones de población:

```powershell
# Verificar las dos fuentes implementadas con el entorno del proyecto.
.\venv\Scripts\python.exe -m pytest tests/test_education.py tests/test_population.py -q
```

`test_population.py` utiliza tablas sintéticas y libros Excel temporales. Comprueba la conservación de Bronze, las notas y filas físicas, el pivote sin doble conteo, las llaves, los componentes faltantes o inválidos y los ceros. Verifica que los casos históricos queden pendientes sin modificar sus poblaciones.

La coincidencia con el archivo real y el notebook se documenta en `docs/etapa_poblacion.md`; las pruebas sintéticas no acreditan por sí solas la calidad del futuro panel integrado.

## Catálogo DIVIPOLA

```powershell
# Verificar educación, población y el catálogo territorial.
.\venv\Scripts\python.exe -m pytest tests/test_education.py tests/test_population.py tests/test_divipola.py -q
```

`test_divipola.py` comprueba conservación, encabezados, códigos únicos, categorías, nombres, departamentos y coordenadas opcionales. Un catálogo sin año no recibe una fecha de vigencia ni una homologación histórica inventadas. Los cruces diagnósticos y las limitaciones se explican en `docs/etapa_divipola.md`.

## Internet fijo

```powershell
# Verificar las cuatro fuentes, incluidos los controles de lectura por bloques.
.\venv\Scripts\python.exe -m pytest tests/test_education.py tests/test_population.py tests/test_divipola.py tests/test_internet.py -q
```

`test_internet.py` comprueba T4 exclusivo, suma entre bloques, duplicados globales, llaves canónicas, nacionales, conservación de la entrada y del literal `NA`, códigos históricos, segmentos ambiguos, ceros y faltantes. Una contribución inválida impide presentar un subtotal como total. Incluye precisión decimal exacta, límites de enteros, desbordamientos y selección del comando de terminal sin recorrer la fuente real.

La conciliación con el CSV completo y las decisiones sobre el segmento `117`, las velocidades y las excepciones territoriales se explican en `docs/etapa_internet.md`. Las 165 pruebas conjuntas aprobadas acreditan esos comportamientos del código; la validez histórica de los casos pendientes requiere evidencia adicional.

## Persistencia Silver

```powershell
# Verificar las reglas de fuentes y la persistencia de tablas y reportes.
.\venv\Scripts\python.exe -m pytest tests -q
```

`test_silver.py` utiliza tablas tipadas y carpetas temporales. Comprueba calidad local frente a aceptación del panel pendiente, llaves, tipos, ceros, faltantes, relectura exacta de Parquet, JSON estricto, huellas y rutas. Inyecta fallos de escritura, verificación y publicación para comprobar que no se dejen salidas nuevas parciales y se restauren los archivos anteriores. Verifica el comando `--silver` sin procesar Bronze.

La ejecución completa con los originales, las cuatro salidas y la interpretación de los porcentajes se documentan en `docs/etapa_silver.md`. La aprobación de las pruebas verifica comportamientos del código; los casos semánticos pendientes se mantienen.

La verificación final aprobó 216 pruebas conjuntas: 51 de Silver y 165 de las fuentes. La ejecución real también generó y reabrió correctamente los cuatro Parquet, y comprobó la integridad de los originales y de los archivos publicados.

## Integración del panel

```powershell
# Comprobar fuentes, Silver e integración sin procesar los originales reales.
.\venv\Scripts\python.exe -m pytest tests -q
```

`test_integration.py` añade 45 casos de conservación del universo y orden MEN, cardinalidad, llaves, tipos, datos originales, faltantes, ceros, extras, departamentos y diagnóstico de las seis variables. Incluye el lector de los cuatro Parquet con su metadata, detección de cambios de contenido y el modo `--integrar`. Distingue coincidencia actual de homologación temporal, y departamento desconocido de contradicción.

`test_export_integration.py` añade 23 casos de publicación, hashes, tipos y recuperación. Simula fallos de preparación y de reemplazo con y sin versiones previas, y protege rutas Bronze, Silver, evidencias anteriores y nombres reservados para indicadores.

`test_integration_metadata.py` añade 13 casos de procedencia y modificaciones durante la integración. Verifica los cuatro Silver, los dos JSON, configuración y código; comprueba que el coordinador detenga la publicación ante un cambio y que la etapa no necesite releer Bronze.

La comprobación conjunta actual aprobó **297 pruebas**: 216 anteriores y 81 de integración, exportación y trazabilidad. La ejecución real guardó y reabrió el panel de 7.850 × 161, y los cuatro Silver y sus dos JSON conservaron sus hashes. Los resultados y la aceptación `no_cumple` se explican en [la etapa de integración](../docs/etapa_integracion.md).

La aprobación de pruebas verifica el funcionamiento del programa. La acreditación territorial, la revisión semántica y el cumplimiento de las metas de datos siguen siendo controles distintos.
