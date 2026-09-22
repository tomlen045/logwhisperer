# logwhisperer

**Log archaeology in one command: timeline / spike detection / trace correlation.** Single-file zero-dependency CLI (Python 3 stdlib). Works on macOS / Linux / Windows.

[简体中文](README.md) | English | [Gitee mirror](https://gitee.com/tomlen/logwhisperer)

## The problem it solves

* Server died, you're tailing thousands of lines to find "the first ERROR after 10pm" → **`lw tail`** prints a per-level timeline: first seen, last seen, duration, count
* "When did ERROR start spiking?" → **`lw spike`** buckets by seconds and flags bursts ≥8x the median baseline
* Chasing one trace id up and down the file → **`lw correlate`** hits plus surrounding context, in one pass
* grep then manually counting → **`lw grep`** regex + time window + hour distribution

## Quick start

```bash
python3 lw.py tail app.log --since "2026-09-22 22:00"
python3 lw.py spike app.log --level ERROR --bucket 60
python3 lw.py correlate app.log --trace TRC-99
python3 lw.py grep app.log --pattern "db timeout" --since "2026-09-22 22:00"
```

## Design principles

* **Facts belong to the script, judgment to you** — lw reports timeline/counts/multipliers, never root-cause conclusions
* **Timestamp-tolerant parsing** — ISO8601 / nginx / syslog / syslog-ISO auto-detected; unparseable lines are counted and skipped loudly, never silently dropped
* **Lines without timestamps never vanish** — folded into the last known time position in `tail`
* **Strictly read-only** — no writes, no deletion, zero network
* **gzip native** — feed `.gz` directly

## Self-test

```bash
python3 scripts/lw.test.py   # 13 cases: 3 time formats / gzip / storm detection / calm-no-false-positive / edge cases
```

## When NOT to use

- Full-text aggregation → loki / elasticsearch
- Live watching → `tail -f` (this is an archaeology tool, not a monitor)
- Logs with no timestamps at all

## License

MIT
