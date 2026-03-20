import os
import tempfile
import traceback
from flask import Flask, request, jsonify, send_from_directory
from main import TradeChecker

app = Flask(__name__, static_folder="static")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/run", methods=["POST"])
def run_checker():
    blotter = request.files.get("blotter")
    positions = request.files.get("positions")

    if not blotter or not positions:
        return jsonify({"error": "Both Blotter and Positions files are required."}), 400

    with tempfile.TemporaryDirectory() as tmpdir:
        blotter_path = os.path.join(tmpdir, blotter.filename)
        positions_path = os.path.join(tmpdir, positions.filename)
        blotter.save(blotter_path)
        positions.save(positions_path)

        try:
            checker = TradeChecker(blotter_file=blotter_path, positions_file=positions_path)
            output = checker.format_output()
        except Exception:
            return jsonify({"error": traceback.format_exc()}), 500

    return jsonify({"output": output})


if __name__ == "__main__":
    app.run(debug=True, port=5050)
