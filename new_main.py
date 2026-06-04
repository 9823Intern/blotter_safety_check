import pandas as pd
from collections import Counter
from pathlib import Path


ALLOWED_TRADES = {
    "Long": ["sl", "bl"],
    "Short": ["ss", "cs"],
    "None": ["bl", "ss"],
}

from datetime import datetime, timedelta
import pytz

# Get current CST date and subtract one day
cst = pytz.timezone('US/Central')
now_cst = datetime.now(cst)
prev_day = now_cst - timedelta(days=1)
date_str = prev_day.strftime("%Y%m%d")

POSITIONS_FILE = Path(
    fr"C:\Users\EnnTurn\Precept Dropbox\PCM Share\Quant Models\Nick GS Position Reports\SRPB_198764_1200680426_Custody_Position_301508_409969_{date_str}.xls"
)

BLOTTER_FILE = Path(__file__).parent / "BlotterEOD06.03.26.xlsx"
BLOTTER_SKIPROWS = 26
RED = "\033[91m"
RESET = "\033[0m"


def load_positions_df(positions_file: Path = POSITIONS_FILE) -> pd.DataFrame:
    """Read the GS custody positions report, raising if it is missing."""
    positions_file = Path(positions_file)
    if not positions_file.exists():
        raise FileNotFoundError(
            f"Positions file not found for {date_str}: {positions_file}"
        )
    return pd.read_excel(
        positions_file, skiprows=8, header=None, engine="calamine"
    )


def analyze(
    blotter_df: pd.DataFrame,
    positions_df: pd.DataFrame,
    skiprows: int = BLOTTER_SKIPROWS,
) -> list[dict]:
    """Run the full blotter check against an already-loaded blotter dataframe."""
    positions_dict = generate_positions_dict(positions_df)
    trades_df = generate_trades_df(blotter_df, skiprows=skiprows)
    return find_trade_errors(positions_dict, trades_df)


def generate_positions_dict(positions_df) -> dict:
    """Return {Ticker: [L/S code, trade-date quantity]}."""
    positions_dict = {}
    for _, row in positions_df.iterrows():
        last_ticker = row.iloc[-1]
        if pd.isna(last_ticker) or (
            isinstance(last_ticker, str) and last_ticker.strip() == ""
        ):
            ticker = row.iloc[4]
        else:
            ticker = last_ticker

        if pd.isna(ticker) or (
            isinstance(ticker, str) and str(ticker).strip() == ""
        ):
            continue

        ticker = str(ticker).strip()
        position = row.iloc[5]
        shares = row.iloc[6]
        if pd.isna(position) or pd.isna(shares):
            continue

        shares = float(shares)
        if ticker not in positions_dict:
            positions_dict[ticker] = [position, shares]
        else:
            positions_dict[ticker][1] += shares
    return positions_dict


def position_state(positions_dict: dict, ticker: str) -> tuple[str, float]:
    """Map net share quantity to (Long|Short|None, absolute share count)."""
    entry = positions_dict.get(ticker)
    if not entry:
        return "None", 0.0

    shares = float(entry[1])
    if shares > 0:
        return "Long", shares
    if shares < 0:
        return "Short", abs(shares)
    return "None", 0.0


def generate_trades_df(
    blotter_df: pd.DataFrame, skiprows: int = BLOTTER_SKIPROWS
) -> pd.DataFrame:
    filtered_df = blotter_df[blotter_df.iloc[:, 0].astype(str) != "C"].copy()
    # Filter the dataframe to only trades where column 19 is exactly "gs-wsf"
    # Also filter out rows where column 11 ("L" in Excel) contains "cros"
    filtered_df = filtered_df[
        (filtered_df.iloc[:, 19].astype(str) == "gs-wsf") &
        (~filtered_df.iloc[:, 11].astype(str).str.lower().str.contains("cros"))
    ].copy()
    filtered_df = filtered_df[filtered_df.iloc[:, 19].astype(str) == "gs-wsf"].copy()
    trades_df = filtered_df
    excel_line = trades_df.index + skiprows + 1
    trades_df = trades_df.iloc[:, [3, 2, 4]].copy()
    trades_df.columns = ["Ticker", "Requested_Trade", "share count"]
    trades_df["line"] = excel_line.values
    trades_df["Requested_Trade"] = (
        trades_df["Requested_Trade"].astype(str).str.strip().str.lower()
    )
    trades_df["Ticker"] = trades_df["Ticker"].astype(str).str.strip()
    trades_df["share count"] = pd.to_numeric(
        trades_df["share count"], errors="coerce"
    )
    return trades_df.reset_index(drop=True)


def _trade_error(
    line: int,
    ticker: str,
    trade_type: str,
    share_count,
    reason: str,
    position: str,
    has_position: bool,
    holdings_side: str,
    holdings_qty: float,
) -> dict:
    return {
        "line": line,
        "Ticker": ticker,
        "Requested_Trade": trade_type,
        "share count": share_count,
        "Position": position,
        "reason": reason,
        "has_position": has_position,
        "holdings_side": holdings_side,
        "holdings_qty": holdings_qty,
    }


def _apply_trade(side: str, qty: float, trade_type: str, trade_size: float) -> tuple[str, float]:
    if trade_type == "sl":
        qty = max(0.0, qty - trade_size)
        return ("None", 0.0) if qty == 0 else ("Long", qty)
    if trade_type == "bl":
        if side == "Short":
            return side, qty
        if side == "None":
            return "Long", trade_size
        return "Long", qty + trade_size
    if trade_type == "ss":
        if side == "Long":
            return side, qty
        if side == "None":
            return "Short", trade_size
        return "Short", qty + trade_size
    if trade_type == "cs":
        qty = max(0.0, qty - trade_size)
        return ("None", 0.0) if qty == 0 else ("Short", qty)
    return side, qty


def check_single_trade(
    line: int,
    ticker: str,
    trade_type: str,
    share_count,
    start_side: str,
    start_qty: float,
    has_position: bool,
) -> dict | None:
    if trade_type not in ALLOWED_TRADES[start_side]:
        return _trade_error(
            line,
            ticker,
            trade_type,
            share_count,
            f"trade not allowed for {start_side} position",
            start_side,
            has_position,
            start_side,
            start_qty,
        )
    return None


def check_multi_trades(
    trades: pd.DataFrame,
    start_side: str,
    start_qty: float,
    has_position: bool,
) -> list[dict]:
    errors = []
    side, qty = start_side, start_qty

    for _, row in trades.iterrows():
        trade_type = row["Requested_Trade"]
        ticker = row["Ticker"]
        share_count = row["share count"]
        line = int(row["line"])

        if trade_type not in ALLOWED_TRADES[side]:
            errors.append(
                _trade_error(
                    line,
                    ticker,
                    trade_type,
                    share_count,
                    f"trade not allowed for {side} position",
                    side,
                    has_position,
                    start_side,
                    start_qty,
                )
            )
            continue

        if side == "Long" and trade_type == "ss" and qty > 0:
            errors.append(
                _trade_error(
                    line,
                    ticker,
                    trade_type,
                    share_count,
                    "short sale before long inventory fully closed (need sl first)",
                    side,
                    has_position,
                    start_side,
                    start_qty,
                )
            )
            continue

        if side == "Short" and trade_type == "bl" and qty > 0:
            errors.append(
                _trade_error(
                    line,
                    ticker,
                    trade_type,
                    share_count,
                    "buy long before short position fully closed (need cs first)",
                    side,
                    has_position,
                    start_side,
                    start_qty,
                )
            )
            continue

        side, qty = _apply_trade(side, qty, trade_type, float(share_count))

    return errors


def find_trade_errors(positions_dict: dict, trades_df: pd.DataFrame) -> list[dict]:
    errors = []
    trade_counts = Counter(trades_df["Ticker"])

    for ticker, count in trade_counts.items():
        ticker_trades = trades_df[trades_df["Ticker"] == ticker]
        start_side, start_qty = position_state(positions_dict, ticker)
        has_position = start_side != "None"

        if count <= 1:
            for _, row in ticker_trades.iterrows():
                err = check_single_trade(
                    int(row["line"]),
                    ticker,
                    row["Requested_Trade"],
                    row["share count"],
                    start_side,
                    start_qty,
                    has_position,
                )
                if err:
                    errors.append(err)
        else:
            errors.extend(
                check_multi_trades(
                    ticker_trades, start_side, start_qty, has_position
                )
            )

    return errors


def _format_error_block(err: dict, number: int) -> list[str]:
    trade_line = (
        f"  #{number}  LINE {err['line']} | {err['Ticker']} | "
        f"{err['Requested_Trade']} | {err['share count']} shares"
    )
    if err["has_position"]:
        detail = (
            f"       Current holdings: {err['holdings_side']} "
            f"({err['holdings_qty']:g} shares)  Reason: {err['reason']}"
        )
    else:
        detail = (
            f"       Position: {err['Position']}  Reason: {err['reason']}"
        )
    block = [trade_line, detail, ""]
    if err["has_position"]:
        block = [
            f"{RED}{line}{RESET}" if line else line for line in block
        ]
    return block


def format_errors(errors: list[dict]) -> str:
    with_position = [e for e in errors if e["has_position"]]
    without_position = [e for e in errors if not e["has_position"]]
    ordered = with_position + without_position

    lines = [
        "Blotter Check Report",
        "=" * 60,
        f"Total ERROR trades: {len(errors)}",
        f"  With current holdings: {len(with_position)}",
        f"  Without current holdings: {len(without_position)}",
        "",
    ]
    if not errors:
        lines.append("No problematic trades detected.")
        return "\n".join(lines)

    if with_position:
        lines.append(f"{RED}--- Trades on tickers WITH a current position ---{RESET}")
        lines.append("")
        for i, err in enumerate(with_position, 1):
            lines.extend(_format_error_block(err, i))

    if without_position:
        lines.append("--- Trades on tickers WITHOUT a current position ---")
        lines.append("")
        offset = len(with_position)
        for i, err in enumerate(without_position, 1):
            lines.extend(_format_error_block(err, offset + i))

    return "\n".join(lines)


def main() -> list[dict]:
    try:
        positions_df = load_positions_df()
    except FileNotFoundError:
        print("Error: Positions File not updated for today")
        exit(1)

    blotter_df = pd.read_excel(
        BLOTTER_FILE, skiprows=BLOTTER_SKIPROWS, header=None, engine="calamine"
    )
    return analyze(blotter_df, positions_df, skiprows=BLOTTER_SKIPROWS)


if __name__ == "__main__":
    flagged = main()
    print(format_errors(flagged))
