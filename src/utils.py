import yaml
import logging
import os
from pathlib import Path

class ETLConfigError(Exception):
    """Excepción personalizada para errores de configuración."""
    pass

class ETLDataError(Exception):
    """Excepción personalizada para errores en la calidad de los datos."""
    pass

def load_config(config_path: str = "config/config.yaml") -> dict:
    """Carga el archivo YAML de configuración y valida su existencia."""
    if not Path(config_path).exists():
        raise ETLConfigError(f"No se encontró el archivo de configuración en: {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    return config

def setup_logger(config: dict) -> logging.Logger:
    """Configura un logger profesional con salida a consola y archivo."""
    log_config = config.get('logging', {})
    log_dir = config['paths']['logs_dir']
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    log_file = os.path.join(log_dir, log_config.get('file_name', 'etl.log'))
    
    logging.basicConfig(
        level=log_config.get('level', 'INFO'),
        format=log_config.get('format', '%(asctime)s - %(levelname)s - %(message)s'),
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(config['project']['name'])

def ensure_directories(config: dict) -> None:
    """Crea los directorios necesarios si no existen (Idempotencia)."""
    paths_to_create = [
        config['paths']['bronze_dir'],
        config['paths']['silver_dir'],
        config['paths']['gold_dir']
    ]
    for path in paths_to_create:
        Path(path).mkdir(parents=True, exist_ok=True)