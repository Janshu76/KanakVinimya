"""Polite, resumable downloader for MCX daily bhavcopy (JSON endpoint used by the MCX website)."""
import argparse
import hashlib
import json
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

BASE_URL = "https://www.mcxindia.com"
ENDPOINT = "/backpage.aspx/GetDateWiseBhavCopy"
OUT_DIR = Path("data/raw_json")
DEFAULT_UA = "KanakVinmya-personal-research/0.1"


class Blocked(Exception):
    """MCX answered 403/429: stop immediately instead of retrying."""


def parse_day(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"bad date {s!r}; use YYYY-MM-DD")


def days_between(start: date, end: date, weekends: bool):
    d = start
    while d <= end:
        if weekends or d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def out_path(day: date, instrument: str) -> Path:
    return OUT_DIR / f"bhavcopy_{instrument}_{day:%Y%m%d}.json"


def fetch(session, base_url, day, instrument, user_agent, retries, backoff):
    url = base_url + ENDPOINT
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/json",
        "Origin": "https://www.mcxindia.com",
        "Referer": "https://www.mcxindia.com/market-data/bhavcopy",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": user_agent,
    }
    payload = json.dumps({"Date": f"{day:%Y%m%d}", "InstrumentName": instrument})
    last = "no attempt made"
    for attempt in range(1, retries + 1):
        try:
            r = session.post(url, headers=headers, data=payload, timeout=30)
            if r.status_code in (403, 429):
                raise Blocked(f"HTTP {r.status_code} from MCX - stopping (do not hammer the server)")
            if r.status_code == 200:
                data = r.json()["d"]["Data"]
                if not isinstance(data, list):
                    raise ValueError("unexpected shape: d.Data is not a list")
                return url, r.text, data
            last = f"HTTP {r.status_code}: {' '.join(r.text.split())[:150]}"
        except Blocked:
            raise
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(min(backoff * 2 ** (attempt - 1), 30))
    raise RuntimeError(last)


def save(day, instrument, url, text, data):
    record = {
        "requested_date": f"{day:%Y%m%d}",
        "instrument": instrument,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": url,
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "n_records": len(data),
        "status": "ok" if data else "empty",          # empty = holiday / no data (kept so we don't ask again)
        "response": json.loads(text),
    }
    path = out_path(day, instrument)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    tmp.replace(path)                                  # atomic: Ctrl+C can't leave a half-written file
    return record["status"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("start", type=parse_day)
    ap.add_argument("end", type=parse_day)
    ap.add_argument("--instrument", default="FUTCOM")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds to wait between requests")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--backoff", type=float, default=2.0)
    ap.add_argument("--weekends", action="store_true", help="also request Saturdays/Sundays")
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    ap.add_argument("--base-url", default=BASE_URL)
    a = ap.parse_args()
    if a.end < a.start:
        print("end date is before start date"); return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    counts = {"ok": 0, "empty": 0, "skipped": 0, "failed": 0}
    failures, consecutive, shown_fields, stopped = [], 0, False, None

    for day in days_between(a.start, a.end, a.weekends):
        if out_path(day, a.instrument).exists():
            counts["skipped"] += 1
            continue
        try:
            url, text, data = fetch(session, a.base_url, day, a.instrument, a.user_agent, a.retries, a.backoff)
        except Blocked as e:
            stopped = str(e); break
        except RuntimeError as e:
            counts["failed"] += 1; consecutive += 1
            failures.append(f"{day:%Y%m%d}: {e}")
            print(f"{day:%Y-%m-%d}  FAILED  {e}")
            if consecutive >= 5:
                stopped = "5 failures in a row - stopping (possible block or outage)"; break
        else:
            consecutive = 0
            status = save(day, a.instrument, url, text, data)
            counts[status] += 1
            print(f"{day:%Y-%m-%d}  {status:<5}  {len(data)} records" + ("  (holiday/no data?)" if not data else ""))
            if data and not shown_fields:
                print("   fields in first record:", sorted(data[0].keys())); shown_fields = True
        time.sleep(a.delay + random.uniform(0, a.delay * 0.5))

    if failures:
        with open(OUT_DIR / "download_errors.log", "a", encoding="utf-8") as f:
            f.write("\n".join(f"{datetime.now():%Y-%m-%d %H:%M} {x}" for x in failures) + "\n")
    print(f"\nDone: {counts}")
    if stopped:
        print("STOPPED:", stopped)
    return 1 if (failures or stopped) else 0


if __name__ == "__main__":
    sys.exit(main())