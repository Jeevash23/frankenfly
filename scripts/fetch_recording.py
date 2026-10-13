"""Download a recorded-fly dataset listed in data/recordings/downloads.json into .cache/recordings/.

    backend/.venv/bin/python scripts/fetch_recording.py rayshubskiy2025-a2_d_13.mat

The file is checked against the recorded size, MD5 and SHA-256 before it is kept. Nothing is
downloaded when a verified copy is already cached. Raw data stays out of version control.
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "data/recordings/downloads.json"
CACHE = ROOT / ".cache/recordings"


def verify(path, record):
    data = path.read_bytes()
    problems = []
    if len(data) != record["bytes"]:
        problems.append(f"{len(data)} bytes instead of {record['bytes']}")
    if hashlib.md5(data).hexdigest() != record["md5"]:
        problems.append("MD5 differs")
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        problems.append("SHA-256 differs")
    return problems


def main():
    records = {r["name"]: r for r in json.loads(RECORDS.read_text())}
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", choices=sorted(records))
    parser.add_argument("--offline", action="store_true", help="Only verify an existing copy")
    args = parser.parse_args()
    record = records[args.name]
    path = CACHE / args.name
    if path.is_file():
        problems = verify(path, record)
        if problems:
            sys.exit(f"{path.relative_to(ROOT)} does not match the record ({'; '.join(problems)}). Delete it to download again.")
        print(f"{path.relative_to(ROOT)} is present and verified ({record['bytes']:,} bytes).")
        return
    if args.offline:
        sys.exit(f"{path.relative_to(ROOT)} is missing. Run without --offline to download {record['bytes'] / 1e6:.1f} MB.")
    CACHE.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    print(f"Downloading {record['bytes'] / 1e6:.1f} MB from {record['url']} …", flush=True)
    request = urllib.request.Request(record["url"], headers={"User-Agent": "digitalfly-fetch-recording"})
    with urllib.request.urlopen(request, timeout=600) as response, part.open("wb") as output:
        while chunk := response.read(1 << 20):
            output.write(chunk)
    problems = verify(part, record)
    if problems:
        part.unlink()
        sys.exit(f"The download does not match the record ({'; '.join(problems)}); nothing was kept.")
    part.rename(path)
    print(f"Saved and verified {path.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
