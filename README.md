# watermark-delta

High-watermark incremental extraction for CSV sources, using only the Python standard library.

It keeps the last watermark (the newest value of a column such as `updated_at`) per source in a small JSON state file. Each run emits only rows newer than that watermark and then advances it. Re-running with no new data gives an empty delta.

## Usage

```bash
python3 watermark_delta.py samples/orders.csv --state watermarks.json -o delta.csv
python3 watermark_delta.py samples/orders.csv --lookback 2h      # re-read 2h for late updates
python3 watermark_delta.py samples/orders.csv --dry-run          # preview, don't move the watermark
```

A JSON run summary goes to stderr:

```json
{"source": "orders.csv", "previous_watermark": null, "new_watermark": "2026-10-13T02:10:00Z", "rows_read": 5, "rows_in_delta": 5, "unparseable": 0, "state_updated": true}
```

## Behaviour

- Rows are included when their timestamp is strictly greater than `watermark - lookback`.
- ISO-8601 timestamps with offsets are compared in UTC, and naive ones are treated as UTC.
- The watermark never moves backwards.
- Unparseable timestamps are counted and skipped.
- The state is written atomically and only after the delta is written, so a failed run never skips data.

## Tests

```bash
python3 -m unittest
```
