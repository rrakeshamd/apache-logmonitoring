import os
from flask import Flask
from dotenv import load_dotenv


def create_app(config_name=None):
    load_dotenv()
    app = Flask(__name__)

    env = config_name or os.environ.get('FLASK_ENV', 'development')
    from app.config import config_map
    app.config.from_object(config_map.get(env, config_map['development']))

    # Start background log tailer threads (local logs)
    from app.services.log_tailer import LogTailerRegistry
    registry = LogTailerRegistry(app.config)
    registry.start()
    app.extensions['log_tailer_registry'] = registry

    # Registry for remote agent-pushed logs
    from app.services.agent_registry import AgentRegistry
    app.extensions['agent_registry'] = AgentRegistry(
        queue_maxsize=app.config['SSE_QUEUE_MAXSIZE']
    )

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.api import api_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api')

    return app
