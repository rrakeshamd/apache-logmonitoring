from flask import Blueprint, render_template, current_app

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    return render_template('index.html',
        llm_enabled=current_app.config['LLM_ENABLED']
    )
