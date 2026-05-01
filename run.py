from app import create_app

app = create_app()

if __name__ == '__main__':
    # threaded=True required: each SSE client holds a long-lived connection open.
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)
