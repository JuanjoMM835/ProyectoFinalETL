# Evidencia oficial para resolver pendientes del ETL

Fecha de consulta: **6 de octubre de 2026**. La fecha UTC concreta de cada descarga está en `data/reference/catalogos_dane.json` y en su archivo de metadatos.

Este documento distingue la identificación de un código en un año, la categoría territorial y la comparabilidad de sus límites entre años. Una coincidencia en un catálogo anual aporta evidencia de identidad para ese año; no demuestra por sí sola que todas las fuentes usen exactamente la misma delimitación ni que el territorio pueda compararse longitudinalmente sin ajustes.

## 1. Referencias territoriales guardadas

El [directorio oficial de servicios del DANE](https://geoportal.dane.gov.co/mparcgis/rest/services) publica carpetas anuales del Marco Geoestadístico Nacional. Se verificaron los esquemas y se guardaron ocho capas completas, sin geometrías, en `data/reference/`. Se mantienen los atributos publicados en `features[].attributes`.

| Año y capa | Archivo local | Registros descargados | Evidencia temporal empleada |
|---|---|---:|---|
| 2018, capa 1 denominada Municipios | `dane_divipola_2018_municipios.json` | 1.122 | Descripción explícita del servicio para 2018; criterio `capa_anual`. |
| 2018, capa 2 denominada Áreas no municipalizadas | `dane_divipola_2018_anm.json` | 20 | El mismo servicio anual; criterio `capa_anual`. |
| 2019, capa Municipio 317 | `dane_mgn_2019_municipios.json` | 1.122 | Descripción oficial del servicio MGN2019; criterio `capa_anual`. `MPIO_NANO` se conserva como atributo de actualización y no se usa para recortar la capa. |
| 2020, capa Municipio 317 | `dane_mgn_2020_municipios.json` | 1.121 | Todos los registros tienen `MPIO_VGNC = 2020`; criterio `anio_registro`. |
| 2021, capa Municipio 317 | `dane_mgn_2021_municipios.json` | 1.121 | Todos los registros tienen `MPIO_VGNC = 2021`; criterio `anio_registro`. |
| 2022, capa Municipio 317 | `dane_mgn_2022_municipios.json` | 1.121 | Todos los registros tienen `MPIO_NANO = 2022`; criterio `anio_registro`. |
| 2023, capa Municipio 317 | `dane_mgn_2023_municipios.json` | 1.121 | Todos los registros tienen `MPIO_NANO = 2023`; criterio `anio_registro`. |
| 2024, capa Municipio 317 | `dane_divipola_2024_municipios.json` | 1.121 | Todos los registros tienen `MPIO_NANO = 2024`; criterio `anio_registro`. |

Referencias oficiales de las ocho capas:

- [DANE DIVIPOLA 2018: Municipios, capa 1](https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DeptosMpiosANM_2018/MapServer/1).
- [DANE DIVIPOLA 2018: Áreas no municipalizadas, capa 2](https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DeptosMpiosANM_2018/MapServer/2).
- [DANE MGN 2019: Municipio, capa 317](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2019/Serv_CapasMGN_2019/MapServer/317).
- [DANE MGN 2020: Municipio, capa 317](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2020/Serv_CapasMGN_2020/MapServer/317).
- [DANE MGN 2021: Municipio, capa 317](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2021/Serv_CapasMGN_2021/MapServer/317).
- [DANE MGN 2022: Municipio, capa 317](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2022/Serv_CapasMGN_2022/MapServer/317).
- [DANE MGN 2023: Municipio, capa 317](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2023/Serv_CapasMGN_2023/MapServer/317).
- [DANE DIVIPOLA MGN 2024: Municipio, capa 317](https://geoportal.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DIVIPOLA_MGN_2024/MapServer/317).

### Esquemas y precauciones

En las capas 2018, `MPIO_CCDGO` contiene el código completo de cinco dígitos; `DPTO_CCDGO` contiene el departamento y `MPIO_CNMBR` el nombre territorial. No hay campo de año por registro ni nombre departamental. No se inventa ese nombre: se puede conservar el descriptivo original de educación y comprobar la identidad mediante el código departamental.

La capa denominada Municipios de 2018 **incluye los 20 códigos de la capa ANM**. Por tanto, las dos descargas no representan 1.142 territorios distintos. Los 20 solapamientos coinciden exactamente en código y departamento. Tras revisar todos los pares, 17 nombres son literalmente iguales y tres difieren únicamente por el marcador categórico terminal `(ANM)` y sus espacios:

| Código | Nombre original en capa 1 | Nombre original en capa ANM |
|---|---|---|
| `97511` | `PACOA (ANM)` | `PACOA` |
| `97777` | `PAPUNAUA(ANM)` | `PAPUNAUA` |
| `97889` | `YAVARATÉ  (ANM)` | `YAVARATÉ `, con un espacio final |

Se aplica una regla específica para **comparar los solapamientos de 2018**, cuando coincidan código y departamento y la segunda capa sustente la categoría ANM: retirar solamente el marcador `(ANM)` situado al final y normalizar los espacios extremos de la comparación. No se retiran otros paréntesis significativos de los nombres ni se utiliza esta excepción para aproximar identidades diferentes. Los nombres originales se conservan; se elige como nombre canónico el de la capa ANM y esa capa tiene prioridad para la categoría. Cualquier otro conflicto de identidad debe producir un error, no una deduplicación arbitraria.

En la primera entrada del manifiesto, `tipo_por_capa` es `null`; en la segunda es `area_no_municipalizada`. Para los demás códigos de 2018 la categoría puede quedar `no_resuelto`, aunque la identidad código-departamento esté sustentada. El nombre de la capa no justifica clasificar todos sus registros como municipios ni trasladar la categoría isla de un catálogo posterior.

En 2019, el código completo es `MPIO_CCNCTNDO`. La ficha del servicio identifica la versión MGN2019; el campo `MPIO_NANO` mezcla valores 2018 y 2019 porque representa actualización de geometría, no la versión completa de la capa. En 2020 y 2021, el código completo es `MPIO_CDPMP` y todos los registros verifican `MPIO_VGNC` igual al año del catálogo. En 2022–2024 se mantiene `MPIO_CDPMP` y la verificación por `MPIO_NANO`. Para 2020–2024 `MPIO_CCDGO` contiene solamente los tres dígitos municipales.

Los servicios 2020 y 2021 tienen descripciones auxiliares contradictorias en su ficha, pero el campo anual de todos los registros coincide con el año consultado. Por eso la regla ejecutable prioriza la evidencia de campo y conserva la discrepancia como advertencia, en lugar de ocultarla.

Los identificadores y huellas completas quedan en los archivos de metadata y en el manifiesto; no se usa un identificador de publicación como sustituto de una fecha territorial. Tampoco `currentVersion` del servidor ArcGIS identifica el año de los datos.

### Integridad y reproducción de la captura

Cada capa se descargó mediante su operación REST `query`, contrastando:

1. `returnCountOnly=true` para obtener el conteo oficial.
2. `returnIdsOnly=true` para conocer todos sus identificadores.
3. Consultas por lotes de hasta 500 `objectIds`, con `outFields=*` y `returnGeometry=false`.
4. Igualdad del número de atributos y del conjunto de identificadores; ausencia de duplicados, errores y páginas truncadas por `exceededTransferLimit`.

El manifiesto registra el esquema, la URL, el criterio temporal, el tamaño y SHA-256 de cada archivo de datos y de metadatos. Los dieciséis archivos de las ocho capas se contrastaron contra esas huellas. Esto comprueba integridad y descarga completa del recurso consultado; no certifica que el organismo haya incorporado todos los cambios legales ocurridos durante el año nominal.

El script comentado `scripts/capturar_catalogos_dane.ps1` permite reproducir la captura desde PowerShell. Escribe referencias en `data/reference/`; no transforma los CSV originales ni las tablas Silver. Una nueva ejecución consulta el servicio nuevamente y puede obtener otra versión: se deben revisar sus huellas y resultados antes de regenerar salidas analíticas.

### Regla aplicada a 2019–2021

Los tres recursos ya están incorporados en el manifiesto y en la resolución territorial. No se interpolan años ni se reasignan códigos.

- [MGN 2019, Municipio 317](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2019/Serv_CapasMGN_2019/MapServer/317): se valida por la descripción oficial del servicio MGN2019 y por el esquema y códigos completos de sus 1.122 registros. `MPIO_NANO` se conserva como atributo de actualización y no se usa para recortar la capa.
- [MGN 2020](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2020/Serv_CapasMGN_2020/MapServer): aunque sus descripciones mezclan 2010 y 2024, los 1.121 registros verifican `MPIO_VGNC=2020`; ese campo sustenta la regla aplicada.
- [MGN 2021](https://geoportal.dane.gov.co/mparcgis/rest/services/MGN2021/Serv_CapasMGN_2021/MapServer): aunque la descripción, título y asunto describen 2024, los 1.121 registros verifican `MPIO_VGNC=2021`; la discrepancia queda como advertencia.

Las discrepancias se conservan como advertencias y no se ocultan. La única limitación territorial restante es la revisión explícita de los cinco códigos históricos; las referencias anuales acreditan identidad para el resto del universo.

## 2. Territorios con cambios históricos

Los códigos `27086`, `27493`, `27615`, `94343` y `94663` permanecen en revisión específica. El nuevo soporte anual no autoriza mover sus cantidades, fundir series o dar por resueltas sus delimitaciones.

### Barrancominas y Mapiripana

La [Gaceta de la Judicatura número 81, de 20 de diciembre de 2019](https://actosadministrativos.ramajudicial.gov.co/GetFile.ashx?url=~%2FApp_Data%2FUpload%2FGACETA81-19.pdf), en los acuerdos PCSJA19-11462 y PCSJA19-11463, identifica la Ordenanza 248 de **24 de julio de 2019** y la creación de Barrancominas con efectos desde el **1 de diciembre de 2019**. Acredita un cambio administrativo dentro del periodo de análisis; no ofrece una equivalencia estadística para sumar o transferir observaciones históricas.

En el catálogo descargado de 2018, `94343` aparece como Barranco Mina y `94663` como Mapiripana en la capa ANM. En las descargas 2022–2024 aparece `94343`, Barrancominas, como municipio; `94663` está ausente. El atributo `MPIO_CRSLCION` de Barrancominas refiere la Ordenanza 261 de **18 de marzo de 2020** como modificación. Este conjunto de evidencias demuestra que cambió la categoría y la representación territorial. No basta para decidir si las cifras anuales del MEN, las proyecciones DANE y los accesos CRC mantienen exactamente el mismo perímetro. Se conserva la revisión para ambos códigos, incluso cuando haya coincidencia anual.

### Nuevo Belén de Bajirá, Riosucio y el código antiguo 27086

La [Registraduría, calendario electoral 2023](https://www.registraduria.gov.co/Calendarios-2023-6812.html), documenta la Ordenanza 180 de **27 de junio de 2023**, el Decreto 0239 de **17 de octubre de 2023** y el referendo de **8 de noviembre de 2023** para la creación del nuevo municipio de Belén de Bajirá. Son acontecimientos verificables; el calendario electoral no es una tabla de homologación DIVIPOLA ni demuestra cómo se repartieron series estadísticas anteriores de Riosucio.

Las ocho capas guardadas contienen `27615`, Riosucio. Ninguna contiene `27493` ni `27086`. En particular, **la descarga nominal 2024 no incluye Nuevo Belén de Bajirá**. Esta ausencia no invalida el registro original que ya existe en otras fuentes: limita lo que puede acreditarse con este recurso concreto. No se completa el catálogo por semejanza de nombres ni se usa una fecha inventada.

Se localizó como referencia adicional el [acta de sesión ordinaria número 005 publicada por la Asamblea del Chocó](https://www.asambleachoco.gov.co/web/wp-content/uploads/2024/07/ACTA-SESION-ORDINARIA-No-005.pdf). El PDF es escaneado, su extracción consultada no devolvió texto y la descarga directa para verificación visual fue rechazada por el servidor. No se utiliza como regla ejecutable de código o vigencia en esta etapa. Su fecha de carpeta web no se interpreta como fecha de creación municipal.

La documentación local de internet identifica dos llaves `27086`, 2018 y 2019, con 2 y 4 accesos. Esos datos se conservan como observaciones de origen. No se transfieren a `27493` y no se suman a Riosucio.

## 3. Cobertura neta educativa superior al 100 %

La [ficha oficial MEN de tasa de cobertura neta, versión V2024](https://portalsineb.mineducacion.gov.co/1782/articles-412165_Cobertura_02_V2024.pdf), en sus observaciones, indica que «se pueden presentar casos con coberturas netas mayores al 100%». Lo explica por migración, diferencias de las proyecciones y estudiantes que asisten a un municipio vecino. Emplea matrícula SIMAT y proyecciones del CNPV 2018 con actualización post COVID publicada en **abril de 2023**; su serie llega a 2024. La ficha consultada no permite fijar una fecha exacta de publicación a partir del nombre del archivo.

Por ello, el ETL puede conservar un valor numérico, finito y no negativo superior a 100 y tratarlo como disponible en la fuente, con una marca informativa. Debe retirar el rechazo automático basado exclusivamente en `cobertura_neta > 100`; no recortarlo a 100 ni sustituirlo por un valor inventado. La metodología general no audita individualmente las 984 observaciones que estaban señaladas. La identidad territorial y las demás comprobaciones del panel siguen siendo requisitos separados.

## 4. Segmento CRC 117: corporativo con accesos adicionales

El [recurso y diccionario actual de Postdata](https://www.postdata.gov.co/resource/accesos-de-internet-fijo-desde-2017-2t) identifica `117` como corporativo con accesos adicionales y lo atribuye a la Resolución 6333 de 2021. La página consultada declara extracción de **30 de junio de 2026** y una serie hasta 2026-T1. Por tanto, es evidencia de significado en el diccionario disponible ahora, no una versión histórica conservada para cada trimestre del proyecto. También señala que la serie desde 2024-T1 es preliminar y está en revisión; esa observación actual no sustituye la procedencia del CSV local.

Se contrastaron dos documentos originales y la norma posterior:

- [Resolución CRC 6333, de 15 de julio de 2021, PDF original](https://www.crcom.gov.co/sites/default/files/webcrc/micrositios/documents/Resoluci%C3%B3n-CRC-6333-de-2021.pdf), formato T.1.3, página 25: enumera corporativo, sin estratificar y uso propio interno, además de estratos residenciales. No enumera en ese apartado la categoría corporativo con accesos adicionales.
- [Documento soporte de simplificación regulatoria 2024](https://www.crcom.gov.co/system/files/Proyectos%20Comentarios/2000-38-3-22/Propuestas/documento-soporte-simplificacion-regulatoria-201224.pdf), revisión **19 de diciembre de 2024**, páginas 168–172: propone incorporar los accesos adicionales de empaquetamientos corporativos y fija una entrada en vigor propuesta para **1 de enero de 2026**. La fecha de vigencia de la plantilla del documento no es la vigencia jurídica de cada regla.
- [Resolución CRC 7811, de 16 de junio de 2025](https://normograma.crcom.gov.co/crc/compilacion/docs/resolucion_crc_7811_2025.htm), artículo 114: la modificación de T.1.3 incorpora esa categoría y rige desde **1 de enero de 2026**. Identifica accesos adicionales dentro de paquetes corporativos con varios accesos del mismo servicio. No acredita automáticamente su tratamiento en datos 2018–2024.

Existe una discrepancia entre el diccionario actual y el texto original de 2021. Se mantiene pendiente la regla histórica de agregación para `117` hasta disponer de una versión histórica o una aclaración oficial suficiente. La documentación local registra 438 contribuciones de este segmento en 132 llaves anuales. Se conservan cantidades y marcas; no se aprueba su suma sin resolver la interpretación, ni se borra el resto de la fila territorial por esa causa.

## 5. Alcance de las decisiones para el panel y los indicadores

La evidencia permite sustituir el uso exclusivo del catálogo actual por referencias de **años exactos 2018–2024**, con comprobación de código y departamento, trazabilidad por fila y exclusión de los cinco códigos históricos señalados. No establece correspondencias retrospectivas entre territorios.

Se deben mantener separados la presencia numérica, la utilizabilidad dentro de cada fuente y la aptitud del dato integrado para calcular un indicador. Corregir el límite educativo no elimina pendientes territoriales o de internet. La categoría territorial de 2018 puede quedar sin resolver sin que ello obligue a inventar una categoría o invalide automáticamente la identidad código-departamento acreditada.

Los porcentajes se recalcularon sobre las llaves reales del universo educativo: 7.833 de 7.850 filas tienen identidad territorial acreditada (99,78 %) y la aceptación del panel cumple la meta del 95 %. Las 17 filas pendientes quedan visibles en los reportes; no se rellenan por inferencia.
