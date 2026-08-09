from flask import Flask, jsonify, render_template

import config as cfg
from bot_runner import state, start_bot, stop_bot, connect_mt5

app = Flask(__name__)


@app.route("/")
def dashboard():
    return render_template("dashboard.html", symbol=cfg.SYMBOL)


@app.route("/api/status")
def api_status():
    resp = jsonify(state.snapshot_view())
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/api/start", methods=["POST"])
def api_start():
    if not state.connected:
        connect_mt5()
    start_bot()
    return jsonify({"ok": True, "running": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    stop_bot()
    return jsonify({"ok": True, "running": False})


if __name__ == "__main__":
    connect_mt5()
    start_bot()  # auto-start on launch
    app.run(host=cfg.FLASK_HOST, port=cfg.FLASK_PORT, debug=False, use_reloader=False)
