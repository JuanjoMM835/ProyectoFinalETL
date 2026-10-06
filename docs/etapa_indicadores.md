# Etapa 6: indicadores y primera Gold exploratoria

Fecha: 2026-10-06. Contrato de datos: **1.1**.

## 1. Qué construye esta etapa

El punto 6 lee el panel integrado ya publicado y añade seis indicadores: accesos de internet fijo por 100 habitantes, porcentaje de población de centros poblados y rural disperso, crecimiento anual de accesos, cobertura neta educativa, deserción y reprobación.

La tabla conserva todo el universo educativo MEN, su orden, los códigos como texto y los valores originales. Cada indicador incorpora un estado y un motivo que explican cuándo puede utilizarse y por qué queda faltante.

La existencia de Parquet y CSV en Gold no implica aceptación de los datos. La metadata y el reporte conservan el estado **exploratorio** y la evaluación de calidad del panel de origen.

## 2. Fórmulas y condiciones

| Indicador | Fórmula | Condiciones |
|---|---|---|
| `accesos_por_100_habitantes` | `accesos_t4 / poblacion_total * 100` | Población positiva y consistente, accesos T4 utilizables e identidad acreditada para el año. |
| `porcentaje_centros_rural` | `poblacion_centros_rural / poblacion_total * 100` | Componentes utilizables de la misma serie, suma consistente, población positiva e identidad acreditada. |
| `crecimiento_anual_accesos` | `(accesos_actuales - accesos_anteriores) / accesos_anteriores * 100` | Mismo código, año anterior consecutivo, accesos T4 utilizables e identidad acreditada en ambos años, y accesos anteriores positivos. |
| `porcentaje_cobertura_neta` | Valor MEN de `cobertura_neta` | Valor numérico no negativo, estado educativo disponible e identidad acreditada. Se conserva un valor superior a 100. |
| `tasa_desercion` | Valor MEN de `desercion` | Valor numérico no negativo, estado educativo disponible e identidad acreditada. |
| `tasa_reprobacion` | Valor MEN de `reprobacion` | Valor numérico no negativo, estado educativo disponible e identidad acreditada. |

Accesos por 100 habitantes expresa conexiones respecto a población; no representa el porcentaje de personas que tienen internet. No se limita automáticamente a 100.

Para crecimiento, un cero actual y un valor anterior positivo producen `-100` %. Un cero anterior impide dividir. Si existe 2020 y 2022 pero falta 2021, no se compara 2022 contra 2020.

En 2018 el crecimiento es `no_aplica`, porque el alcance inicial no incorpora 2017. Este caso se distingue de un reporte faltante de 2019–2024. Todos permanecen en el denominador del reporte; crecimiento no forma parte de las seis variables críticas con meta de completitud del contrato.

Los cálculos verifican de nuevo componentes y signos. Las operaciones con conteos utilizan enteros de Python antes de convertir el resultado a decimal, para evitar desbordamientos o pérdida de diferencias pequeñas entre cifras grandes.

## 3. Estados, motivos y diagnóstico

Para cada indicador existen:

- El valor canónico, por ejemplo `accesos_por_100_habitantes`.
- `estado_accesos_por_100_habitantes`: `disponible`, `no_calculable`, `no_aplica` o `pendiente_revision`.
- `motivo_accesos_por_100_habitantes`: explica la condición observada.
- Las tres columnas equivalentes con sufijo `_diagnostico`.

Los valores canónicos requieren identidad territorial acreditada. Los campos `_diagnostico` aplican los controles locales de población e internet sin acreditar identidad temporal. Sirven para conciliar fórmulas y revisar datos; no deben confundirse con indicadores territoriales validados.

Ejemplos de motivos son `sin_reporte_t4`, `poblacion_total_no_positiva`, `componentes_poblacionales_inconsistentes`, `revision_internet`, `sin_anio_anterior_consecutivo`, `accesos_anteriores_no_positivos`, `identidad_territorial_pendiente` e `identidad_anterior_pendiente`.

Los tres indicadores educativos exponen los valores MEN con nombres Gold propios; no sobrescriben las columnas fuente. La aceptación del conjunto crítico y la calculabilidad de cada indicador se reportan por separado.

## 4. Índice de prioridad

El Gold incorpora `indice_prioridad` y `categoria_prioridad` para priorizar municipios con déficit de conectividad, mayor deserción y menor cobertura. El score se calcula como:

`0,4 * déficit_conectividad + 0,3 * deserción + 0,3 * déficit_cobertura`.

Los componentes se normalizan a 0–1 con límites fijos 0–100: conectividad y cobertura se convierten en déficit (`1 - valor/100`) y deserción se usa como riesgo (`valor/100`). Los valores fuente no se modifican; el recorte solo aplica a la transformación del índice. Menos de 0,33 es prioridad **baja**, desde 0,33 y menor que 0,66 es **media**, y desde 0,66 es **alta**. Si falta un componente, el índice queda `no_calculable` y no se asigna una categoría.

También se publican las columnas `_diagnostico`, que permiten revisar candidatos locales sin presentarlos como identidad territorial acreditada.

## 5. Revisión de cobertura neta con evidencia MEN

El criterio anterior dejaba pendientes los 984 valores de cobertura neta superiores a 100. La [ficha oficial MEN de cobertura neta, serie 2015–2024](https://portalsineb.mineducacion.gov.co/1782/articles-412165_Cobertura_02_V2024.pdf) explica que esa magnitud puede aparecer por estimaciones poblacionales, migración y estudiantes que se desplazan entre municipios.

Se corrigió la exclusión automática: las cifras se conservan, junto con `cobertura_neta_superior_100_informativo`. No se recortan a 100 ni se certifica individualmente cada observación. Los negativos, conversiones inválidas y no finitos mantienen sus restricciones; deserción y reprobación mantienen su control porcentual.

Esta revisión de elegibilidad se registró en **contrato 1.1** y configuración. Por ese cambio se regeneraron Silver y el panel antes de calcular Gold: el lector exige coincidencia de versión de contrato y evita utilizar una integración anterior como si incorporara la nueva regla.

## 6. Evidencia territorial por código y año

Se conservaron copias locales de ocho capas oficiales DANE: las dos capas 2018 de territorios y ANM, las capas 2019–2023 y la capa 2024. El manifiesto `data/reference/catalogos_dane.json` registra referencias, campos reales, conteos oficiales, identificadores, tamaños, huellas y fecha de captura. Los archivos de metadata de los servicios acompañan los atributos.

Las descargas se verificaron contra el conteo oficial y la lista completa de identificadores, en lotes que no exceden el límite del servicio. No se descargan geometrías ni se asume que una primera página contiene todos los territorios.

La resolución es selectiva: código y departamento deben concordar para el año exacto, sin contradicciones de las fuentes. La evidencia se conserva en `evidencia_homologacion`, `vigencia_desde` y `vigencia_hasta`. Una resolución de 2024 no se extiende a 2019.

La capa 2018 denominada Municipios incluye también las 20 ANM de la segunda capa. Se concilian las coincidencias exactas sin duplicar filas; la capa ANM acredita su categoría. Para los demás registros 2018 sin un campo de categoría explícito, el tipo puede permanecer `no_resuelto` aunque se haya acreditado identidad por código y departamento. No se aplica retroactivamente el tipo del CSV actual.

Los años 2019–2021 se incorporan con reglas explícitas: MGN2019 se acredita por la versión del servicio; MGN2020 y MGN2021 por `MPIO_VGNC` en todos sus registros. Las discrepancias de metadatos quedan como advertencias y no se ocultan.

Los códigos históricos `27086`, `27493`, `27615`, `94343` y `94663` permanecen excluidos de la resolución automática. Para ellos se requieren reglas de correspondencia y comparabilidad temporal específicas. No se transfieren cifras ni se deduce un año de vigencia de una noticia o del nombre de un archivo.

Las referencias y límites de estas decisiones se explican en [evidencia_pendientes.md](evidencia_pendientes.md).

## 7. Responsabilidades del código

| Archivo | Responsabilidad |
|---|---|
| `src/transform/clean_education.py` | Implementa la revisión MEN sin alterar los valores observados. |
| `src/transform/resolve_territory.py` | Lee referencias locales verificadas y acredita identidades por código y año exactos. |
| `src/transform/integrate_sources.py` | Incorpora esa evidencia antes de calcular las máscaras de calidad del panel. |
| `src/extract/read_integrated.py` | Verifica el panel y sus dos JSON, contrato, periodo, filas y tipos. |
| `src/transform/build_indicators.py` | Calcula seis indicadores, sus estados, candidatos de diagnóstico e índice de prioridad. |
| `src/load/execution_metadata.py` | Confirma integridad de las entradas y reglas durante la ejecución. |
| `src/load/export_gold.py` | Prepara y verifica Parquet, CSV y dos JSON; publica con respaldo y recuperación. |
| `main.py` | Coordina `--gold` y conserva un log independiente. |
| `scripts/capturar_catalogos_dane.ps1` | Permite reproducir la captura de las ocho referencias oficiales verificadas. |

Los nuevos módulos y el script contienen comentarios en español. Los lectores no vuelven a limpiar los datos y los exportadores no recalculan indicadores.

## 8. Rutas y ejecución

Desde la raíz de `ProyectoFinalETL`:

```powershell
# Regenerar Silver si cambió el contrato, Bronze o las reglas de limpieza.
.\venv\Scripts\python.exe main.py --silver

# Integrar los Silver y las referencias anuales locales.
.\venv\Scripts\python.exe main.py --integrar

# Calcular y exportar indicadores desde ese panel.
.\venv\Scripts\python.exe main.py --gold

# Verificar todas las etapas con datos sintéticos y carpetas temporales.
.\venv\Scripts\python.exe -m pytest tests -q
```

Cuando las entradas siguen vigentes, basta repetir `--gold`. Los cuatro modos `--fuente`, `--silver`, `--integrar` y `--gold` son excluyentes.

Las salidas de indicadores son:

- `data/gold/indicadores_municipio_anio.parquet`.
- `data/gold/indicadores_municipio_anio.csv`.
- `logs/reporte_indicadores.json`.
- `logs/metadata_indicadores.json`.
- `logs/etl_indicadores.log`.

Parquet conserva tipos y faltantes. La copia CSV utiliza UTF-8 con BOM y no lleva índice técnico. Sus consumidores deben leer códigos como texto; abrir CSV con conversión automática en Excel puede quitar ceros iniciales.

El exportador relee ambos formatos. En Parquet compara tipos y valores exactamente; en CSV compara textos, códigos, enteros y posiciones de faltantes, y usa tolerancia mínima para decimales. Los cuatro archivos se preparan antes de publicar y la metadata se reemplaza al final; ante fallos se recupera la versión anterior.

## 9. Pendientes que siguen visibles

El segmento CRC `117` requiere conciliar su definición histórica. Se conserva la información observada y su revisión: no se presupone que los accesos adicionales sean exclusivos ni se resta un segmento de otro.

La evidencia de los cinco códigos históricos y la interpretación histórica del segmento CRC `117` siguen pendientes. La velocidad ponderada y participación de fibra permanecen desactivadas porque sus variables/metodología no están validadas. El índice de prioridad ya está implementado y documentado, pero conserva el estado exploratorio general de la Gold.
