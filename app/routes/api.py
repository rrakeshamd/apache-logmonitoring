import json
import queue as _queue

from flask import Blueprint, Response, current_app, request, jsonify, stream_with_context

api_bp = Blueprint('api', __name__)


@api_bp.route('/stream/<log_name>')
def stream(log_name):
    """
    SSE endpoint. log_name is 'access' or 'error'.
    Each SSE event is a JSON-encoded parsed log entry.
    """
    registry = current_app.extensions['log_tailer_registry']
    tailer = registry.get(log_name)
    if tailer is None:
        return jsonify({'error': f'Unknown log: {log_name}'}), 404

    # Use error parser for any log whose name contains "error", access parser otherwise
    if 'error' in log_name:
        from app.services.log_parser import parse_error_line as parse
    else:
        from app.services.log_parser import parse_access_line as parse

    def generate():
        q = tailer.subscribe()
        try:
            while True:
                try:
                    raw_line = q.get(timeout=15)
                    parsed = parse(raw_line)
                    payload = json.dumps(parsed)
                    yield f'data: {payload}\n\n'
                except _queue.Empty:
                    # SSE heartbeat comment to keep connection alive through proxies
                    yield ': heartbeat\n\n'
        except GeneratorExit:
            pass
        finally:
            tailer.unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':    'no-cache',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering if behind nginx
        },
    )


@api_bp.route('/config')
def get_config():
    registry = current_app.extensions['log_tailer_registry']
    return jsonify({
        'log_names':   registry.all_names(),
        'llm_enabled': current_app.config['LLM_ENABLED'],
    })


@api_bp.route('/logs')
def list_logs():
    """Returns all discovered log files with name, path, and size."""
    registry = current_app.extensions['log_tailer_registry']
    return jsonify(registry.all_info())


@api_bp.route('/refresh', methods=['POST'])
def refresh_logs():
    """Re-scan LOG_DIR for new *.log files and start tailers for any found."""
    registry = current_app.extensions['log_tailer_registry']
    registry.refresh()
    return jsonify({'log_names': registry.all_names()})


@api_bp.route('/agent/push', methods=['POST'])
def agent_push():
    """
    Receives a single log line from a remote log agent.
    Body: {"server": "web-01", "log_name": "access", "line": "..."}
    Header: X-Agent-Key must match AGENT_SECRET.
    """
    key = request.headers.get('X-Agent-Key', '')
    if key != current_app.config['AGENT_SECRET']:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json(force=True, silent=True) or {}
    server   = data.get('server', '').strip()
    log_name = data.get('log_name', '').strip()
    line     = data.get('line', '').strip()

    if not server or not log_name or not line:
        return jsonify({'error': 'server, log_name, and line are required'}), 400

    agent_registry = current_app.extensions['agent_registry']
    agent_registry.push(server, log_name, line)
    return '', 204


@api_bp.route('/stream/<server>/<log_name>')
def stream_agent(server, log_name):
    """
    SSE endpoint for a remote agent's log stream.
    server    — server name as registered by the agent
    log_name  — log name (access, error, etc.)
    """
    agent_registry = current_app.extensions['agent_registry']

    if 'error' in log_name:
        from app.services.log_parser import parse_error_line as parse
    else:
        from app.services.log_parser import parse_access_line as parse

    def generate():
        q = agent_registry.subscribe(server, log_name)
        try:
            while True:
                try:
                    raw_line = q.get(timeout=15)
                    parsed   = parse(raw_line)
                    payload  = json.dumps(parsed)
                    yield f'data: {payload}\n\n'
                except _queue.Empty:
                    yield ': heartbeat\n\n'
        except GeneratorExit:
            pass
        finally:
            agent_registry.unsubscribe(server, log_name, q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


@api_bp.route('/servers')
def list_servers():
    """Returns all server names that have connected via agent."""
    agent_registry = current_app.extensions['agent_registry']
    return jsonify({'servers': agent_registry.registered_servers()})


@api_bp.route('/servers/<server>/logs')
def list_server_logs(server):
    """Returns log names registered for a specific remote server."""
    agent_registry = current_app.extensions['agent_registry']
    return jsonify({'log_names': agent_registry.registered_logs(server)})


@api_bp.route('/analyze', methods=['POST'])
def analyze():
    """
    Accepts JSON body: {"lines": ["...", ...], "log_type": "access"}
    Returns LLM analysis, or HTTP 503 if LLM is disabled.
    """
    if not current_app.config['LLM_ENABLED']:
        return jsonify({
            'error':       'LLM integration is disabled. Set LLM_ENABLED=true in .env to enable.',
            'llm_enabled': False,
        }), 503

    data = request.get_json(force=True, silent=True) or {}
    lines = data.get('lines', [])
    if not lines:
        return jsonify({'error': 'No lines provided'}), 400

    max_lines = current_app.config['LLM_CHUNK_SIZE']
    lines = lines[-max_lines:]

    from app.services.llm_hook import analyze_with_claude
    try:
        result = analyze_with_claude(
            log_lines=lines,
            api_key=current_app.config['ANTHROPIC_API_KEY'],
            model=current_app.config['LLM_MODEL'],
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 502
    except Exception:
        current_app.logger.exception("LLM analysis failed")
        return jsonify({'error': 'Internal error during LLM analysis'}), 500
