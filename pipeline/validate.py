import sys
from pathlib import Path
import pandas as pd
import yaml

def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    return ok

def validate(parquet_path: Path, config_path: Path) -> bool:
    df = pd.read_parquet(parquet_path)
    cfg = yaml.safe_load(config_path.read_text())["contracts"]
    results = []

    # 1. every symbol in the data is known to the config
    unknown = set(df.symbol) - set(cfg)
    results.append(check("all symbols are in config", not unknown, str(sorted(unknown)) if unknown else ""))

    # 2. no duplicate (symbol, expiry, date)
    dups = df.duplicated(["symbol", "expiry", "trade_date"]).sum()
    results.append(check("no duplicate contract-day rows", dups == 0, f"({dups} duplicates)"))

    # 3. lot size implied by the file matches config
    t = df[df.traded].copy()
    t["implied_lot_g"] = t.volume_000 * 1000 / t.volume_lots
    t["cfg_lot_g"] = t.symbol.map({k: v["lot_grams"] for k, v in cfg.items()})
    bad = t[(t.implied_lot_g - t.cfg_lot_g).abs() > 1e-6]
    results.append(check("implied lot size == config lot size", bad.empty, f"({len(bad)} mismatches)"))

    # 4. ghost rows (no trades) must have blank OHLC and Close == Previous Close
    g = df[~df.traded]
    ghost_ok = g[["open", "high", "low"]].isna().all().all() and (g.close == g.prev_close).all()
    results.append(check("no-trade rows look like carried-forward prices", ghost_ok, f"({len(g)} ghost rows)"))

    # 5. traded rows must have low <= close <= high, and all prices positive
    ok_range = ((t.low <= t.close) & (t.close <= t.high)).all()
    results.append(check("traded rows: low <= close <= high", ok_range))
    results.append(check("all closes are positive", (df.close > 0).all()))

    # 6. expiry must be after trade date
    results.append(check("expiry is on/after trade date", (df.expiry >= df.trade_date).all()))

    # Warnings: config facts not yet verified
    for sym, spec in cfg.items():
        if not spec["verified"]:
            print(f"[WARN] {sym}: purity/quote unit not verified against MCX spec yet")

    return all(results)

if __name__ == "__main__":
    ok = validate(Path(sys.argv[1]), Path(sys.argv[2]))
    print("\nOVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)