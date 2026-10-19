"""Download the CBS road-accident Public Use Files (2020-2024) from data.gov.il.

Source: Central Bureau of Statistics, "Road accidents with casualties 2020-2024, PUF"
https://data.gov.il/dataset/2023-puf   (licence: Other (Open))

One row per police-reported accident with casualties. A PUF is de-identified by
design: no names, ID numbers or vehicle plates. The file host blocks scripted
downloads, so this pages through data.gov.il's datastore API instead.

    python scripts/download_data.py      # -> data/raw/accidents_<year>.csv, dictionary_<year>.csv
"""
import csv
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
BASE = "https://data.gov.il/api/3/action/"
PAGE = 5000


def api(action: str, **params) -> dict:
    url = BASE + action + "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.load(r)["result"]
        except Exception:  # noqa: BLE001 - flaky public API: retry with backoff
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def fetch_table(resource_id: str) -> tuple[list[str], list[dict]]:
    rows, offset, fields = [], 0, None
    while True:
        res = api("datastore_search", resource_id=resource_id, limit=PAGE, offset=offset)
        fields = fields or [f["id"] for f in res["fields"] if f["id"] != "_id"]
        rows += res["records"]
        offset += PAGE
        if offset >= res["total"]:
            return fields, rows


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for r in api("package_show", id="2023-puf")["resources"]:
        name = r.get("name", "")
        if not (name.startswith("data -") or name.startswith("Dictionary -")):
            continue
        year = name.split("-")[-1].strip()
        kind = "accidents" if name.startswith("data") else "dictionary"
        dest = RAW / f"{kind}_{year}.csv"
        if dest.exists():
            continue
        fields, rows = fetch_table(r["id"])
        if kind == "dictionary":  # stored as one comma-joined column: "MS_TAVLA,KOD,TEUR"
            col = fields[0]
            text = "\n".join([col] + [row[col] for row in rows])
            dest.write_text(text, encoding="utf-8")
        else:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
            dest.write_text(buf.getvalue(), encoding="utf-8")
        print(f"{dest.name:22s} {len(rows):>7,} rows")


if __name__ == "__main__":
    main()
