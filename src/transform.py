import pandas as pd
import os
import unicodedata
import logging
from src.utils import ETLDataError

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Limpia los nombres de las columnas: quita tildes, espacios y convierte a snake_case.

    """
    new_columns = []
    for col in df.columns:
        # 1. Quitar tildes y caracteres especiales , lo mismo que en arqui , eliminamos caracteres especiales y tildes para evitar problemas al momento de hacer analitica
        col = unicodedata.normalize('NFKD', str(col)).encode('ascii', 'ignore').decode('utf-8')
        # 2. Pasar a minúsculas, quitar espacios y reemplazar por guion bajo
        col = col.strip().lower().replace(' ', '_').replace('-', '_')
        # 3. Quitar caracteres no alfanuméricos pero no quitamos el guion bajo, para evitar problemas en SQL y Pandas
        col = ''.join(c for c in col if c.isalnum() or c == '_')
        new_columns.append(col)
    df.columns = new_columns
    return df

def transform_education_to_silver(config: dict, logger: logging.Logger) -> None:
    """
    Limpia, tipa y estandariza los datos crudos del MEN desde la capa Bronze.
    """
    logger.info("INICIANDO CAPA SILVER: Limpieza y Estandarización de MEN Educación")
    
    bronze_path = os.path.join(config['paths']['bronze_dir'], "men_educacion_preescolar_basica_media_20261002.parquet")
    silver_dir = config['paths']['silver_dir']
    
    try:
        # 1. Lectura desde Bronze
        df = pd.read_parquet(bronze_path)
        initial_rows = len(df)
        logger.info(f"Datos crudos cargados desde Bronze. Filas: {initial_rows}, Columnas: {len(df.columns)}")
        
        # 2. Limpieza de nombres de columnas  sin tildes
        df = clean_column_names(df)
        logger.info("Nombres de columnas estandarizados a snake_case.")
        
        # 3. Tratamiento de Nulos ya que investigando el ministerio usa  guiones o espacios vacíos
        df.replace(['-', ' ', 'N/A', 'NA', ''], pd.NA, inplace=True)
        
        # 4. Tipado Estricto hacemos la conversion de tipos de datos , en este caso de strings a números, para garantizar consistencia
        # Columnas que son porcentajes necesitan quitar el '%' y cambiar ',' por '.'
        percent_cols = [col for col in df.columns if 'tasa' in col or 'cobertura' in col or 'porcentaje' in col]
        for col in percent_cols:
            df[col] = df[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '.', regex=False)
            df[col] = pd.to_numeric(df[col], errors='coerce')
            logger.info(f"Columna de porcentaje '{col}' limpiada y convertida a numérico.")

        # Columnas numéricas normales
        numeric_cols = ['ano', 'poblacion_5_16', 'desercion', 'aprobacion']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                logger.info(f"Columna '{col}' convertida a tipo numérico.")
        
        # 5. Eliminación de duplicados
        df.drop_duplicates(inplace=True)
        logger.info(f"Duplicados eliminados: {initial_rows - len(df)}")
        
        # 6. Eliminar columnas de Bronze ya no las necesitamos en Silver

        cols_to_drop = [c for c in df.columns if c.startswith('_')]
        df.drop(columns=cols_to_drop, inplace=True, errors='ignore')
        
        # 7. Guardamos en Silver
        output_path = os.path.join(silver_dir, "men_educacion_clean.parquet")
        df.to_parquet(output_path, index=False)
        logger.info(f"Capa Silver completada. Datos limpios guardados en: {output_path}")
        
    except Exception as e:
        logger.error(f"Error en la capa Silver: {str(e)}")
        raise ETLDataError("Fallo en la transformación Silver.") from e

def transform_education_to_gold(config: dict, logger: logging.Logger) -> None:
    """
    Genera tablas de KPIs a partir de la capa Silver
    """
    logger.info(">>> INICIANDO CAPA GOLD: Generación de KPIs de Negocio")
    
    silver_path = os.path.join(config['paths']['silver_dir'], "men_educacion_clean.parquet")
    gold_dir = config['paths']['gold_dir']
    
    try:
        df = pd.read_parquet(silver_path)
        
        # 1. Filtrar la fila NACIONAL para no sesgar los promedios
        df = df[df['departamento'].str.upper() != 'NACIONAL']
        df = df[df['municipio'].str.upper() != 'NACIONAL']
        
        # 2. Estandarizar mayúsculas/minúsculas en texto esto es buena practica porque como sabemos no es lo mismo "ARCHIPIÉLAGO" vs "Archipiélago", 
        df['departamento'] = df['departamento'].str.upper().str.strip()
        df['municipio'] = df['municipio'].str.upper().str.strip()
        
        # KPI 1: Promedios de Educación por Departamento  
        # Debemos asegurar que los no haya duplicidad en los departementos y municipios, por eso hacemos un groupby antes de sacar los promedios
        kpi_dept = df.groupby('departamento').agg(
            total_poblacion_5_16=('poblacion_5_16', 'sum'),
            promedio_tasa_matriculacion=('tasa_matriculacion_5_16', 'mean'),
            promedio_cobertura_neta=('cobertura_neta', 'mean')
        ).reset_index()
        
        kpi_dept['promedio_tasa_matriculacion'] = kpi_dept['promedio_tasa_matriculacion'].round(2)
        kpi_dept['promedio_cobertura_neta'] = kpi_dept['promedio_cobertura_neta'].round(2)
        
        output_path_dept = os.path.join(gold_dir, "kpi_educacion_por_departamento.parquet")
        kpi_dept.to_parquet(output_path_dept, index=False)
        logger.info(f"KPI por Departamento guardado en: {output_path_dept}")

        # KPI 2: Top 10 Municipios Agrupando primero para evitar duplicados
        # Agrupamos por municipio y departamento para consolidar la población total
        df_mun_agg = df.groupby(['municipio', 'departamento']).agg(
            poblacion_5_16=('poblacion_5_16', 'sum'),
            tasa_matriculacion_5_16=('tasa_matriculacion_5_16', 'mean'),
            cobertura_neta=('cobertura_neta', 'mean')
        ).reset_index()
        
        # Ahora sí, ordenamos y sacamos el Top 10 real
        kpi_mun = df_mun_agg.sort_values(by='poblacion_5_16', ascending=False).head(10)
        
        output_path_mun = os.path.join(gold_dir, "top_10_municipios_poblacion.parquet")
        kpi_mun.to_parquet(output_path_mun, index=False)
        logger.info(f"Top 10 Municipios guardado en: {output_path_mun}")
        
    except Exception as e:
        logger.error(f"Error en la capa Gold: {str(e)}")
        raise ETLDataError("Fallo en la transformación Gold.") from e