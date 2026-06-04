"""Web frontend for the blotter safety check.

Drag/drop a blotter file or paste an Excel grid; the contents are used as the
``BLOTTER_FILE`` input for the existing trade-error analysis in ``new_main``.

Run with::

    python app.py

then open http://127.0.0.1:5000 in a browser.
"""

from __future__ import annotations

import traceback
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request

import new_main

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

EXCEL_EXTS = {".xlsx", ".xls", ".xlsm", ".xlsb"}


def _read_excel_bytes(data: bytes, skiprows: int) -> pd.DataFrame:
    return pd.read_excel(
        BytesIO(data), skiprows=skiprows, header=None, engine="calamine"
    )


def read_blotter_from_upload(data: bytes, filename: str, skiprows: int) -> pd.DataFrame:
    """Parse an uploaded blotter file into the same shape as ``BLOTTER_FILE``."""
    ext = Path(filename or "").suffix.lower()
    if ext in EXCEL_EXTS:
        return _read_excel_bytes(data, skiprows)
    if ext == ".csv":
        return pd.read_csv(BytesIO(data), skiprows=skiprows, header=None)
    # Unknown extension: try Excel first, then CSV as a fallback.
    try:
        return _read_excel_bytes(data, skiprows)
    except Exception:
        return pd.read_csv(BytesIO(data), skiprows=skiprows, header=None)


def read_blotter_from_paste(text: str, skiprows: int) -> pd.DataFrame:
    """Parse an Excel/CSV grid pasted as text (tab- or comma-separated)."""
    sep = "\t" if "\t" in text else ","
    return pd.read_csv(
        StringIO(text),
        sep=sep,
        header=None,
        skiprows=skiprows,
        engine="python",
        on_bad_lines="skip",
    )


@app.route("/")
def index():
    return render_template("index.html", default_skiprows=new_main.BLOTTER_SKIPROWS)


@app.route("/check", methods=["POST"])
def check():
    try:
        skiprows = int(request.form.get("skiprows", new_main.BLOTTER_SKIPROWS))
    except (TypeError, ValueError):
        skiprows = new_main.BLOTTER_SKIPROWS

    # Build the blotter dataframe from either an uploaded file or pasted text.
    source = None
    try:
        uploaded = request.files.get("file")
        pasted = request.form.get("pasted", "").strip()

        if uploaded and uploaded.filename:
            blotter_df = read_blotter_from_upload(
                uploaded.read(), uploaded.filename, skiprows
            )
            source = uploaded.filename
        elif pasted:
            blotter_df = read_blotter_from_paste(pasted, skiprows)
            source = "pasted grid"
        else:
            return jsonify({"ok": False, "error": "No blotter file or pasted grid provided."}), 400
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the UI
        return jsonify({
            "ok": False,
            "error": f"Could not read the blotter input: {exc}",
            "detail": traceback.format_exc(),
        }), 400

    # Load positions report (fixed path / date logic lives in new_main).
    try:
        positions_df = new_main.load_positions_df()
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"Could not read the positions file: {exc}",
            "detail": traceback.format_exc(),
        }), 500

    # Run the existing analysis.
    try:
        errors = new_main.analyze(blotter_df, positions_df, skiprows=skiprows)
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"Analysis failed: {exc}",
            "detail": traceback.format_exc(),
        }), 500

    with_position = [e for e in errors if e.get("has_position")]
    without_position = [e for e in errors if not e.get("has_position")]

    return jsonify({
        "ok": True,
        "source": source,
        "skiprows": skiprows,
        "summary": {
            "total": len(errors),
            "with_position": len(with_position),
            "without_position": len(without_position),
        },
        "with_position": with_position,
        "without_position": without_position,
    })


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
