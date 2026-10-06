# ProyectoFinalETL

ETL de educación MEN, población DANE, internet fijo CRC y catálogo DIVIPOLA para Colombia, periodo 2018–2024. Las decisiones de universo, llaves, transformaciones y calidad están en [el contrato de datos](docs/contrato_datos.md).

## Estado actual

Están implementadas extracción, limpieza y persistencia Silver; integración sobre el universo MEN; seis indicadores con estados y motivos; y un índice de prioridad con categorías baja, media y alta. Se incorporan referencias oficiales DANE de 2018–2024 con reglas explícitas para 2019–2021. La Gold mantiene estado exploratorio, aunque la aceptación del panel ya cumple la meta de homologación; el detalle queda en los reportes.

| Capa | Contenido actual |
|---|---|
| Bronze | Cuatro archivos originales en `data/bronze/`. |
| Silver | Cuatro tablas independientes generadas con `main.py --silver`. |
| Referencias | Ocho capas oficiales DANE, fichas de metadata y manifiesto en `data/reference/`. |
| Evidencias | Reportes, metadatos e historial independientes para Silver, integración e indicadores en `logs/`. |
| Gold | Panel integrado exploratorio e indicadores con su copia CSV, estados y diagnóstico. |

## Ejecución

El entorno del proyecto utiliza las dependencias fijadas en `requirements.txt`. Desde esta carpeta, en PowerShell:

```powershell
# Guardar las cuatro tablas Silver y sus reportes.
.\venv\Scripts\python.exe main.py --silver

# Integrar las cuatro tablas Silver ya publicadas y guardar diagnósticos.
.\venv\Scripts\python.exe main.py --integrar

# Calcular indicadores desde el panel y publicar Parquet, CSV y reportes.
.\venv\Scripts\python.exe main.py --gold

# Preparar una sola fuente en memoria para estudiar sus controles.
.\venv\Scripts\python.exe main.py --fuente educacion
.\venv\Scripts\python.exe main.py --fuente poblacion
.\venv\Scripts\python.exe main.py --fuente divipola
.\venv\Scripts\python.exe main.py --fuente internet

# Comprobar las reglas de todas las etapas implementadas.
.\venv\Scripts\python.exe -m pytest tests -q
```

`--silver`, `--integrar`, `--gold` y `--fuente` son modos excluyentes. Sin estos argumentos se conserva educación como fuente predeterminada. `--config` permite indicar otro YAML; las rutas se resuelven desde la raíz de este proyecto. Integración consume Silver; indicadores consumen el panel integrado. Después de un cambio de contrato o reglas de limpieza se regenera Silver y se repiten las etapas en ese orden.

La fuente de internet se lee por bloques y su control global puede tardar varios minutos. No se modifica Bronze. La escritura prepara y verifica todos los archivos antes de publicar; una nueva ejecución reemplaza las salidas configuradas y conserva el historial del log.

## Resultados Silver

- `data/silver/educacion_limpia.parquet`.
- `data/silver/poblacion_limpia.parquet`.
- `data/silver/internet_municipio_anio.parquet`.
- `data/silver/divipola_limpia.parquet`.
- `logs/reporte_calidad.json`.
- `logs/metadata_ejecucion.json`.
- `logs/etl_pipeline.log`.

Parquet conserva tipos y faltantes. El reporte Silver describe la calidad local y mantiene `no_evaluada` la aceptación de un panel que esa etapa no construye. Los reportes siguientes evalúan integración e indicadores. Cobertura neta >100 permanece como marca informativa compatible con la ficha MEN; los códigos históricos y el segmento corporativo adicional CRC continúan en revisión.

## Resultados de integración

- `data/gold/panel_integrado_exploratorio.parquet`: universo MEN completo y procedencia de fuentes y evidencia anual.
- `logs/reporte_integracion.json`: coincidencias y calidad sobre todo el universo MEN.
- `logs/metadata_integracion.json`: procedencia Silver, versiones y hashes.
- `logs/etl_integracion.log`: historial del proceso.

La coincidencia del CSV DIVIPOLA actual se conserva aparte de la acreditación por código y año de las nuevas referencias oficiales. Las resoluciones registran URL y vigencia de un año; los nombres MEN originales siguen disponibles en columnas de procedencia. Los años sin evidencia y los códigos históricos no se homologan por similitud de nombres.

## Resultados de indicadores

- `data/gold/indicadores_municipio_anio.parquet`.
- `data/gold/indicadores_municipio_anio.csv`.
- `logs/reporte_indicadores.json`.
- `logs/metadata_indicadores.json`.
- `logs/etl_indicadores.log`.

Se calculan accesos por 100 habitantes, porcentaje de población de centros poblados y rural disperso, crecimiento anual de accesos, cobertura neta, deserción y reprobación. Cada uno tiene estado y motivo. También se calcula `indice_prioridad` con `categoria_prioridad` y versión diagnóstica. Los campos `_diagnostico` aplican controles locales sin acreditar identidad; los valores canónicos exigen identidad territorial documentada. En 2018 el crecimiento no aplica; en los demás años exige el año anterior consecutivo, accesos anteriores positivos e identidad acreditada en ambos años.

CSV se verifica al exportar, pero sus consumidores deben leer los códigos como texto. La velocidad ponderada y fibra permanecen pendientes porque todavía no hay variables y metodología validadas para ellas. El tablero no forma parte de esta etapa.

## Documentación y código

Consultar [educación](docs/etapa_educacion.md), [población](docs/etapa_poblacion.md), [DIVIPOLA](docs/etapa_divipola.md), [internet fijo](docs/etapa_internet.md), [persistencia Silver](docs/etapa_silver.md), [integración inicial](docs/etapa_integracion.md), [indicadores actuales](docs/etapa_indicadores.md) y [evidencia oficial y pendientes](docs/evidencia_pendientes.md).

`main.py` coordina; `src/extract/` lee originales; `src/transform/` prepara y valida; `src/load/` persiste y documenta la ejecución. Las pruebas y sus reglas se explican en [tests/README.md](tests/README.md).
