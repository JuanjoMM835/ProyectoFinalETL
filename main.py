import sys
from src.utils import load_config, setup_logger, ensure_directories
from src.extract import extract_education_stats
from src.transform import transform_education_to_silver, transform_education_to_gold # <-- Nueva importación

def main():
    try:
        # 1. Inicialización
        config = load_config()
        logger = setup_logger(config)
        ensure_directories(config)
        
        logger.info("="*60)
        logger.info(f"INICIANDO PIPELINE ETL - {config['project']['name'].upper()}")
        logger.info("="*60)
        
        # 2. Ejecución de Capas 
       
        extract_education_stats(config, logger)
        
        # Silver
        transform_education_to_silver(config, logger)
        
        # Gold
        transform_education_to_gold(config, logger)
        
        logger.info("="*60)
        logger.info("PIPELINE ETL (FASES BRONZE, SILVER Y GOLD) FINALIZADO CON ÉXITO")
        logger.info("="*60)
        
    except Exception as e:
        print(f"\n ERROR CRÍTICO EN EL PIPELINE: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()