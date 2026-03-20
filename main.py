import pandas as pd



class TradeChecker:
    def __init__(self, blotter_file: str, positions_file: str):
        self.blotter_file = blotter_file
        self.positions_file = positions_file

    

    def main(self):
        """
        Main src function \n
        Check the blotter and positions files for potentially illogical trades.
        """
        self.blotter_df = pd.read_excel(self.blotter_file, skiprows=26, header=None)
        self.blotter_df = self.blotter_df[self.blotter_df.iloc[:, 11] != 'cros']
        positions_full = pd.read_excel(self.positions_file, skiprows=16, header=None)
        self.positions_df = positions_full.iloc[:, [0, 1, 2, 5]][positions_full.iloc[:, 0] == "Common Stock"]
        # Drop the Asset Class (First Column) and rename the remaining columns
        self.positions_df = self.positions_df.iloc[:, 1:]
        self.positions_df.columns = ["Position","Ticker", "Shares"]
        allowed_pairs = {
            "Long": ["sl", "bl"],
            "Short": ["ss", "cs"],
            "None": ["bl", "ss"]
        }
        
        aggregated_positions = {}
        for _, row in self.positions_df.iterrows():
            ticker = row.iloc[1]
            position = row.iloc[0]
            shares = row.iloc[2]
            if ticker not in aggregated_positions:
                aggregated_positions[ticker] = {"Position": position, "Shares": shares}
            else:
                aggregated_positions[ticker]["Shares"] += shares
        
        problematic_trades = []
        for _, row in self.blotter_df.iterrows():

            # Map the Ticker for each trade (row) to the aggregated positions, check if the trade is allowed
            trade_type = row.iloc[2]
            ticker = row.iloc[3]
            trade_size = row.iloc[4]
            if ticker not in aggregated_positions:
                aggregated_positions[ticker] = {"Position": "None", "Shares": 0}

            allowed_trades = allowed_pairs[aggregated_positions[ticker]["Position"]]
            
            if trade_type not in allowed_trades:
                print(f"Trade {trade_type} on {ticker} with {trade_size} shares is not allowed. Position is: {aggregated_positions[ticker]['Position']}, but attempting to {trade_type} {trade_size} shares")
                problematic_trades.append({
                    "Trade Type": trade_type,
                    "Ticker": ticker,
                    "Trade Size": trade_size,
                    "Position": aggregated_positions[ticker]["Position"],
                    "Allowed Trades": allowed_trades
                })
            """
            Stage 2: Check for a potential set of trades that flip the position. 
            E.g.: Long -> Neutral -> Short through Sell Long, Sell Short
            
            OR

                  Short -> Neutral -> Long through Close Short, Buy Long
            """

            
            
        return problematic_trades


    def format_output(self) -> str:
        problematic_trades = self.main()
        lines = []
        lines.append(f"Blotter Check Report")
        lines.append("=" * 60)
        lines.append(f"Total problematic trades found: {len(problematic_trades)}")
        lines.append("")
        for i, trade in enumerate(problematic_trades, 1):
            lines.append(f"  #{i}")
            lines.append(f"    Ticker:         {trade['Ticker']}")
            lines.append(f"    Trade Type:     {trade['Trade Type']}")
            lines.append(f"    Trade Size:     {trade['Trade Size']}")
            lines.append(f"    Position:       {trade['Position']}")
            lines.append(f"    Allowed Trades: {', '.join(trade['Allowed Trades'])}")
            lines.append("")
        if not problematic_trades:
            lines.append("  No problematic trades detected.")
        return "\n".join(lines)


if __name__ == "__main__":
    checker = TradeChecker(blotter_file="Blotter.xlsx", positions_file="Positions.xls")
    print(checker.format_output())