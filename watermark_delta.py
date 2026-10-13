#!/usr/bin/env python3
"""watermark-delta: high-watermark incremental extraction for CSV sources.

Standard library only. Keeps a small JSON state file holding the last
watermark (the highest value of a column such as updated_at) per source.
Each run reads the CSV, keeps only rows strictly newer than the stored
watermark, minus an optional lookback for late updates, writes them as the
delta, and advances the watermark to the newest value seen.

The state is only advanced after the delta is written, so a failed run never
skips data. Use --dry-run to preview without touching the state.
"""
import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone


def parse_ts(text):
    t = (text or "").strip()
    if not t:
        return None
    if t[-1] in "Zz":
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def fmt(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_state(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(path, state):
    """Write state atomically so a crash never leaves a half-written file."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def select_delta(rows, column, watermark=None, lookback=timedelta(0)):
    """Return (delta_rows, new_watermark, skipped_unparseable).

    A row is included when its timestamp is > (watermark - lookback).
    With no watermark, every parseable row is included (initial load).
    The new watermark is the max timestamp seen across ALL parseable rows,
    never lower than the old one.
    """
    cutoff = watermark - lookback if watermark else None
    delta, newest, bad = [], watermark, 0
    for row in rows:
        ts = parse_ts(row.get(column))
        if ts is None:
            bad += 1
            continue
        if newest is None or ts > newest:
            newest = ts
        if cutoff is None or ts > cutoff:
            delta.append(row)
    return delta, newest, bad


def parse_lookback(text):
    t = (text or "0").strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    seconds = float(t[:-1]) * units[t[-1]] if t and t[-1] in units else float(t)
    if seconds < 0:
        raise ValueError("lookback must not be negative")
    return timedelta(seconds=seconds)


def main(argv=None):
    p = argparse.ArgumentParser(description="Extract rows newer than the stored watermark from a CSV.")
    p.add_argument("source", help="source CSV")
    p.add_argument("--column", default="updated_at", help="watermark column (default: updated_at)")
    p.add_argument("--state", default="watermarks.json", help="JSON state file (default: watermarks.json)")
    p.add_argument("--name", help="state key for this source (default: the source file name)")
    p.add_argument("--lookback", default="0", help="re-read this much before the watermark for late updates, e.g. 15m, 2h")
    p.add_argument("-o", "--output", default="-", help="delta CSV path (default: stdout)")
    p.add_argument("--dry-run", action="store_true", help="do not update the state file")
    args = p.parse_args(argv)

    name = args.name or os.path.basename(args.source)
    try:
        lookback = parse_lookback(args.lookback)
    except ValueError as e:
        print(f"watermark-delta: bad --lookback: {e}", file=sys.stderr)
        return 2

    state = load_state(args.state)
    old = parse_ts(state.get(name, {}).get("watermark")) if name in state else None

    with open(args.source, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if args.column not in fields:
            print(f"watermark-delta: column {args.column!r} not in {fields}", file=sys.stderr)
            return 2
        rows = list(reader)

    delta, new, bad = select_delta(rows, args.column, old, lookback)

    out = sys.stdout if args.output == "-" else open(args.output, "w", newline="", encoding="utf-8")
    try:
        w = csv.DictWriter(out, fieldnames=fields)
        w.writeheader()
        w.writerows(delta)
    finally:
        if out is not sys.stdout:
            out.close()

    summary = {
        "source": name,
        "previous_watermark": fmt(old) if old else None,
        "new_watermark": fmt(new) if new else None,
        "rows_read": len(rows),
        "rows_in_delta": len(delta),
        "unparseable": bad,
        "state_updated": False,
    }
    if not args.dry_run and new is not None and new != old:
        state[name] = {"column": args.column, "watermark": fmt(new)}
        save_state(args.state, state)
        summary["state_updated"] = True
    print(json.dumps(summary), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
