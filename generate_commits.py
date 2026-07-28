#!/usr/bin/env python3
"""Backdated commit generator built on `git fast-import`.

Streams the whole history into git in one pass instead of shelling out to
`git commit` per commit, which is what made the previous version take tens of
minutes for a year of history.
"""

import argparse
import datetime
import random
import subprocess
import sys

DEFAULT_START = datetime.date(2025, 1, 1)
AUTHOR_NAME = "Viltrumlik"
AUTHOR_EMAIL = "viltrumlik@gmail.com"
BRANCH = "main"
LOG_PATH = "activity.log"

# Only the last N lines are kept in the file so every blob stays a few hundred
# bytes. Appending forever would store ~17k copies of a file growing to 600KB.
WINDOW = 10

# Local working hours, so the author date never slides into an adjacent day in
# another timezone. GitHub buckets a commit by its author date + offset.
HOUR_START = 9
HOUR_END = 21

MESSAGES = [
    "Update activity log",
    "Refresh log entries",
    "Append daily log entry",
    "Record activity",
    "Rotate log window",
    "Sync activity log",
    "Trim stale log lines",
    "Log routine activity",
    "Checkpoint activity log",
    "Update log rotation",
]


def tz_offset_string(when):
    """Return the local UTC offset for `when` as +HHMM."""
    local = datetime.datetime.now().astimezone().tzinfo
    offset = local.utcoffset(when)
    if offset is None:
        return "+0000"
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}{(total % 3600) // 60:02d}"


def day_timestamps(day, count, rng):
    """Return `count` strictly increasing datetimes inside the day's window."""
    span_start = day.replace(hour=HOUR_START, minute=0, second=0)
    span_end = day.replace(hour=HOUR_END, minute=0, second=0)
    span = int((span_end - span_start).total_seconds())

    # Sample without replacement so two commits never share a second, then sort
    # to keep the history monotonic. The old version emitted days out of order
    # because eight threads raced through the queue.
    seconds = sorted(rng.sample(range(span), count))
    return [span_start + datetime.timedelta(seconds=s) for s in seconds]


def data_block(payload):
    """fast-import's counted-data format: length in bytes, then the bytes."""
    blob = payload.encode("utf-8")
    return b"data " + str(len(blob)).encode("ascii") + b"\n" + blob + b"\n"


def build_stream(start, end, min_commits, max_commits, rng):
    """Yield the fast-import command stream, one chunk per commit."""
    window = []
    mark = 0
    total = 0

    day = start
    while day <= end:
        count = rng.randint(min_commits, max_commits)
        midnight = datetime.datetime.combine(day, datetime.time())

        for stamp in day_timestamps(midnight, count, rng):
            total += 1
            window.append(f"{stamp.isoformat(sep=' ')}  entry {total}")
            del window[:-WINDOW]

            body = "\n".join(window) + "\n"
            when = f"{int(stamp.timestamp())} {tz_offset_string(stamp)}"
            ident = f"{AUTHOR_NAME} <{AUTHOR_EMAIL}> {when}"

            mark += 1
            blob_mark = mark
            mark += 1

            yield b"blob\n"
            yield f"mark :{blob_mark}\n".encode("ascii")
            yield data_block(body)

            yield f"commit refs/heads/{BRANCH}\n".encode("ascii")
            yield f"mark :{mark}\n".encode("ascii")
            yield f"author {ident}\n".encode("utf-8")
            yield f"committer {ident}\n".encode("utf-8")
            yield data_block(rng.choice(MESSAGES))
            # No `from` line: fast-import chains onto the branch tip itself.
            yield f"M 100644 :{blob_mark} {LOG_PATH}\n\n".encode("utf-8")

        day += datetime.timedelta(days=1)

    yield b"done\n"


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=datetime.date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=datetime.date.fromisoformat, default=datetime.date.today())
    parser.add_argument("--min", dest="min_commits", type=int, default=10)
    parser.add_argument("--max", dest="max_commits", type=int, default=50)
    parser.add_argument("--seed", type=int, default=None, help="fix the RNG for a reproducible run")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)

    if args.start > args.end:
        sys.exit("Error: --start must not be after --end")
    if not 1 <= args.min_commits <= args.max_commits:
        sys.exit("Error: need 1 <= --min <= --max")

    span = (HOUR_END - HOUR_START) * 3600
    if args.max_commits > span:
        sys.exit(f"Error: --max cannot exceed {span} (one commit per second in the daily window)")

    head = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD"],
        capture_output=True, text=True,
    )
    if head.returncode == 0:
        sys.exit("Error: this repo already has commits. Run in a fresh repo.")

    days = (args.end - args.start).days + 1
    print(f"{days} kun: {args.start} -> {args.end}, kuniga {args.min_commits}-{args.max_commits} commit")

    rng = random.Random(args.seed)
    proc = subprocess.Popen(
        ["git", "fast-import", "--quiet", "--done"],
        stdin=subprocess.PIPE,
    )
    for chunk in build_stream(args.start, args.end, args.min_commits, args.max_commits, rng):
        proc.stdin.write(chunk)
    proc.stdin.close()

    if proc.wait() != 0:
        sys.exit(f"Error: git fast-import failed ({proc.returncode})")

    subprocess.run(["git", "reset", "--hard", BRANCH], check=True, capture_output=True)
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    print(f"Tayyor: {count} commit, branch '{BRANCH}'")


if __name__ == "__main__":
    main(sys.argv[1:])
