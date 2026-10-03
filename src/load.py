import pandas as pd
import os
import logging

def load_gold_to_bi(config: dict, logger: logging.Logger) -> None:
    """
    Simula la carga de la capa Gold a una herramienta de base de datos
    """
    logger.info("INICIANDO CAPA LOAD: Preparación para Análisis")
    
    gold_dir = config['paths']['gold_dir']
    files = [f for f in os.listdir(gold_dir) if f.endswith('.parquet')]
    
    if not files:
        logger.warning("No hay archivos en la capa Gold para cargar.")
        return
        
    for file in files:
        file_path = os.path.join(gold_dir, file)
        df = pd.read_parquet(file_path)
        
        # 1. Exportar a CSV 
        csv_path = file_path.replace('.parquet', '.csv')
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        logger.info(f"Archivo exportado para BI: {csv_path}")
        
        # 2. Aquí iría la carga a Base de Datos 
        # Lo hacemos igual que en Arquitectura , debemos tener un manifiesto donde estara la config de la  conexion a la base de datos.
        # Con esa conexion vamos a poblar la base de datos , creando las tablas y haciendo los inserts, finalmeente hacemos la conexion a power bi
        # Para mostrar el resultado del ETL y los KPIS 
        
    logger.info("Carga final completada. Datos listos para Análisis-BI-CD.")
