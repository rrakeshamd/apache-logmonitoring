import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    # Directory containing *.log files to monitor
    LOG_DIR = os.environ.get('LOG_DIR', '/var/log/apache2')

    # LLM integration — disabled by default
    LLM_ENABLED       = os.environ.get('LLM_ENABLED', 'false').lower() == 'true'
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
    LLM_MODEL         = os.environ.get('LLM_MODEL', 'claude-3-5-haiku-20241022')
    LLM_CHUNK_SIZE    = int(os.environ.get('LLM_CHUNK_SIZE', '20'))

    # SSE per-client queue depth (drop oldest if client is slow)
    SSE_QUEUE_MAXSIZE = 500


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_map = {
    'development': DevelopmentConfig,
    'production':  ProductionConfig,
}
