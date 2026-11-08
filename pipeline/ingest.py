# pipeline/ingest.py
import hashlib
from io import StringIO
from pathlib import Path
import pandas as pd

COLS = {
    "Date": "trade_date", "Instrument Name": "instrument", "Symbol": "symbol",
    "Expiry Date": "expiry", "Option Type": "option_type", "Strike Price": "strike",
    "Open": "open", "High": "high", "Low": "low", "Close": "close",
    "Previous Close": "prev_close", "Volume(Lots)": "volume_lots",
    "Volume(In 000's)": "volume_000", "Value(Lacs)": "value_lacs",
    "Open Interest(Lots)": "oi_lots",
}

def load_bhavcopy(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    df = pd.read_html(StringIO(raw.decode("utf-8", errors="replace")))[0]
    df = df.rename(columns=COLS)
    df["symbol"] = df["symbol"].str.strip()                       # clean padded symbols
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%d %b %Y")
    df["expiry"] = pd.to_datetime(df["expiry"], format="%d%b%Y")
    df["volume_000"] = df["volume_000"].str.extract(r"([\d.]+)")[0].astype(float)
    df["traded"] = df["volume_lots"] > 0                          # flags the ghost rows
    df["source_file"] = path.name
    df["source_sha256"] = hashlib.sha256(raw).hexdigest()         # provenance
    return df

if __name__ == "__main__":
    df = load_bhavcopy(Path("data/raw/BhavCopyDateWise_06112026.xls"))
    gold = df[(df.instrument == "FUTCOM") & df.symbol.str.startswith("GOLD")]
    Path("data/processed").mkdir(parents=True, exist_ok=True)
    gold.to_parquet("data/processed/gold_2026-11-06.parquet", index=False)
    print(len(df), "rows read;", len(gold), "gold futures rows saved")