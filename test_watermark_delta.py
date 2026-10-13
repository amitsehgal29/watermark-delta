import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import timedelta

import watermark_delta as wd

ROWS = [
    {"id": "1", "updated_at": "2026-10-12T08:00:00Z"},
    {"id": "2", "updated_at": "2026-10-12T10:00:00Z"},
    {"id": "3", "updated_at": "bad"},
    {"id": "4", "updated_at": "2026-10-13T06:00:00+04:00"},  # 02:00Z
]


class SelectTests(unittest.TestCase):
    def test_initial_load_takes_all_parseable(self):
        delta, new, bad = wd.select_delta(ROWS, "updated_at")
        self.assertEqual([r["id"] for r in delta], ["1", "2", "4"])
        self.assertEqual(wd.fmt(new), "2026-10-13T02:00:00Z")
        self.assertEqual(bad, 1)

    def test_strictly_greater_than_watermark(self):
        wm = wd.parse_ts("2026-10-12T10:00:00Z")
        delta, _, _ = wd.select_delta(ROWS, "updated_at", wm)
        self.assertEqual([r["id"] for r in delta], ["4"])

    def test_lookback_rereads_recent_rows(self):
        wm = wd.parse_ts("2026-10-12T10:00:00Z")
        delta, _, _ = wd.select_delta(ROWS, "updated_at", wm, timedelta(hours=1))
        self.assertEqual([r["id"] for r in delta], ["2", "4"])

    def test_watermark_never_moves_backwards(self):
        wm = wd.parse_ts("2026-10-20T00:00:00Z")
        delta, new, _ = wd.select_delta(ROWS, "updated_at", wm)
        self.assertEqual(delta, [])
        self.assertEqual(new, wm)

    def test_lookback_parsing(self):
        self.assertEqual(wd.parse_lookback("15m"), timedelta(minutes=15))
        self.assertEqual(wd.parse_lookback("90"), timedelta(seconds=90))
        with self.assertRaises(ValueError):
            wd.parse_lookback("-1h")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.src = os.path.join(self.dir, "src.csv")
        self.state = os.path.join(self.dir, "state.json")
        with open(self.src, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["id", "updated_at"])
            w.writeheader()
            w.writerows(ROWS)

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = wd.main([self.src, "--state", self.state, "--name", "orders", *extra])
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        return code, rows, json.loads(err.getvalue().strip().splitlines()[-1])

    def test_second_run_is_empty_and_state_persists(self):
        code, rows, s = self.run_cli()
        self.assertEqual((code, len(rows), s["state_updated"]), (0, 3, True))
        code, rows, s = self.run_cli()
        self.assertEqual((len(rows), s["state_updated"]), (0, False))
        with open(self.state) as f:
            self.assertEqual(json.load(f)["orders"]["watermark"], "2026-10-13T02:00:00Z")

    def test_dry_run_leaves_state_alone(self):
        _, rows, s = self.run_cli("--dry-run")
        self.assertEqual((len(rows), s["state_updated"]), (3, False))
        self.assertFalse(os.path.exists(self.state))


if __name__ == "__main__":
    unittest.main()
