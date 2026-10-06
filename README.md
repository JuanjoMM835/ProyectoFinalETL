# ProyectoFinalETL

ETL de educación MEN, población DANE, internet fijo CRC y catálogo DIVIPOLA para Colombia, periodo 2018–2024. Las decisiones de universo, llaves, transformaciones y calidad están en [el contrato de datos](docs/contrato_datos.md).

## Estado actual

Están implementadas la extracción y limpieza de las cuatro fuentes y la persistencia Silver con controles, log y metadatos. Las excepciones se conservan. La integración y los indicadores Gold corresponden a los puntos siguientes; la aceptación del panel todavía no se declara resuelta.

| Capa | Contenido actual |
|---|---|
| Bronze | Cuatro archivos originales en `data/bronze/`. |
| Silver | Cuatro tablas independientes generadas con `main.py --silver`. |
| Evidencias | Calidad y metadatos de la última publicación, e historial del log en `logs/`. |
| Gold | Pendiente de integración e indicadores. |

## Ejecución

El entorno del proyecto utiliza las dependencias fijadas en `requirements.txt`. Desde esta carpeta, en PowerShell:

```powershell
# Guardar las cuatro tablas Silver y sus reportes.
.\venv\Scripts\python.exe main.py --silver

# Preparar una sola fuente en memoria para estudiar sus controles.
.\venv\Scripts\python.exe main.py --fuente educacion
.\venv\Scripts\python.exe main.py --fuente poblacion
.\venv\Scripts\python.exe main.py --fuente divipola
.\venv\Scripts\python.exe main.py --fuente internet

# Comprobar las reglas de todas las etapas implementadas.
.\venv\Scripts\python.exe -m pytest tests -q
```

`--silver` y `--fuente` son modos excluyentes. Sin estos argumentos se conserva educación como fuente predeterminada. `--config` permite indicar otro YAML; los archivos de datos se resuelven desde la raíz de este proyecto.

La fuente de internet se lee por bloques y su control global puede tardar varios minutos. No se modifica Bronze. La escritura prepara y verifica todos los archivos antes de publicar; una nueva ejecución reemplaza las salidas configuradas y conserva el historial del log.

## Resultados Silver

- `data/silver/educacion_limpia.parquet`.
- `data/silver/poblacion_limpia.parquet`.
- `data/silver/internet_municipio_anio.parquet`.
- `data/silver/divipola_limpia.parquet`.
- `logs/reporte_calidad.json`.
- `logs/metadata_ejecucion.json`.
- `logs/etl_pipeline.log`.

Parquet conserva tipos y faltantes. Los reportes distinguen presencia numérica y utilización local de las fuentes; la aceptación del panel integrado permanece `no_evaluada`. Los códigos históricos, la cobertura neta pendiente y el segmento corporativo adicional de internet siguen identificados para revisión.

## Documentación y código

Consultar [educación](docs/etapa_educacion.md), [población](docs/etapa_poblacion.md), [DIVIPOLA](docs/etapa_divipola.md), [internet fijo](docs/etapa_internet.md) y [persistencia Silver](docs/etapa_silver.md).

`main.py` coordina; `src/extract/` lee originales; `src/transform/` prepara y valida; `src/load/` persiste y documenta la ejecución. Las pruebas y sus reglas se explican en [tests/README.md](tests/README.md).
