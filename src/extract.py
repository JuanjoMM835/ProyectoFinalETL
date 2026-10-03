import pandas as pd
import os
from datetime import datetime
import logging
from src.utils import ETLDataError

def extract_education_stats(config: dict, logger: logging.Logger) -> None:
    """
    Extrae el dataset de estadísticas educativas del MEN y lo deposita en la capa Bronze.
    """
    logger.info(">>> INICIANDO CAPA BRONZE: Extracción de MEN Educación")
    
    source_info = config['sources']['education_stats']
    source_path = source_info['path']
    bronze_dir = config['paths']['bronze_dir']
    
    try:
        # 1. Lectura del CSV usando las opciones del YAML separador, encoding, etc.
        # En el manifiesto yaml debe de estar el separador para cada dataset, ya que algunos usan coma, otros punto y coma, otros tabulador, etc.
        # En este dataset el separador es una , 
        read_opts = source_info.get('read_options', {})
        logger.info(f"Leyendo archivo fuente: {source_path} con opciones: {read_opts}")
        
        df = pd.read_csv(source_path, **read_opts)
        logger.info(f"Datos crudos cargados exitosamente. Filas: {len(df)}, Columnas: {len(df.columns)}")
        
        # 2. Data Lineage Linaje de datos: Agregar metadatos de auditoría
        df['_ingested_at'] = datetime.now().isoformat()
        df['_source_file'] = source_info['file_name']
        df['_layer'] = 'bronze'
        
        # 3. Guardar en Bronze , Formato Parquet visualizamos los datos en Jupiter , cree un notebook para leer los datos de bronce y de gold.
        #  Para ver estos datos se van a la terminal y le dan pip install jupyterlab y luego escriben jupyter lab y se abre un navegador con la interfaz de jupyter, ahi crean un notebook y leen los datos de bronce y gold
        # Parquet mantiene los tipos de datos y es el estándar
        output_filename = f"{source_info['file_name'].replace('.csv', '')}.parquet"
        output_path = os.path.join(bronze_dir, output_filename)
        
        df.to_parquet(output_path, index=False)
        logger.info(f"Capa Bronze completada. Archivo guardado en: {output_path}")
        
    except FileNotFoundError:
        logger.error(f"Archivo fuente no encontrado: {source_path}")
        raise
    except Exception as e:
        logger.error(f"Error inesperado en la extracción: {str(e)}")
        raise ETLDataError("Fallo en la extracción de datos del MEN.") from e