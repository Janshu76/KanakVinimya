import hashlib
import re
import sys
from pathlib import Path
import pandas as pd
from ingest import load_bhavcopy

RAW = Path("data/raw")
INTERIM = Path("data/interim")          # one small gold-only Parquet per raw file (a cache)
OUT = Path("data/processed/gold_all.parquet")

def requested_date(path: Path) -> pd.Timestamp:
    m = re.search(r"(\d{2})(\d{2})(\d{4})", path.stem)      # ddmmyyyy in the file name
    if not m:
        raise ValueError(f"no ddmmyyyy date in file name {path.name}")
    d, mth, y = map(int, m.groups())
    return pd.Timestamp(year=y, month=mth, day=d)

def gold_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df.instrument == "FUTCOM") & df.symbol.str.startswith("GOLD")]

def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main() -> int:
    files = sorted(RAW.glob("BhavCopy*.xls"))
    if not files:
        print(f"No files found in {RAW}"); return 1
    INTERIM.mkdir(parents=True, exist_ok=True)

    frames, problems, reused = [], [], 0
    for f in files:
        try:
            req = requested_date(f)
            cache = INTERIM / f"{f.stem}.parquet"

            # reuse the cached result only if it came from exactly this file's bytes
            if cache.exists():
                cached = pd.read_parquet(cache)
                if len(cached) and cached.source_sha256.iloc[0] == sha256_of(f):
                    frames.append(cached); reused += 1
                    continue

            df = load_bhavcopy(f)
            returned = sorted(pd.Timestamp(x) for x in df.trade_date.unique())
            if returned != [req]:
                problems.append(f"{f.name}: requested {req.date()} but file contains "
                                f"{[str(x.date()) for x in returned]}  -> quarantined")
                continue                                     # never silently substitute a date
            gold = gold_only(df)
            if gold.empty:
                problems.append(f"{f.name}: no gold futures rows found")
                continue
            gold.to_parquet(cache, index=False)              # only validated files enter the cache
            frames.append(gold)
        except Exception as e:                               # a bad file must be reported, not skipped quietly
            problems.append(f"{f.name}: could not be read ({type(e).__name__}: {e})")

    if not frames:
        print("No valid files."); [print("PROBLEM", p) for p in problems]; return 1

    data = pd.concat(frames, ignore_index=True)
    dups = data.duplicated(["symbol", "expiry", "trade_date"]).sum()
    if dups:
        problems.append(f"{dups} duplicate contract-day rows after combining files")
    data = data.sort_values(["trade_date", "symbol", "expiry"]).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(OUT, index=False)

    # ---- coverage report ----
    days = pd.to_datetime(sorted(data.trade_date.unique()))
    first, last = days[0], days[-1]
    missing = [d.date() for d in pd.bdate_range(first, last) if d not in set(days)]
    print(f"Files read: {len(files)}  | accepted: {len(frames)} (from cache: {reused})  | problems: {len(problems)}")
    print(f"Trading days: {len(days)}  ({first.date()} to {last.date()})")
    print(f"Weekdays with no file (holiday or missing? check MCX calendar): {missing}")
    print(f"Rows: {len(data)}  | ghost rows (no trade): {(~data.traded).sum()}")
    print(f"Saved -> {OUT}")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0

if __name__ == "__main__":
    sys.exit(main())