"""Summarize an Eltima Serial Port Monitor 'Table view' text redirect/export.

Collapses the TX/RX byte stream into lines and prints:
  * port open/close and configuration IOCTLs (baud, line control, handshake, ...)
  * every TX command with its RX reply (consecutive repeats collapsed unless --all)
  * counts per command

Usage: python tools/parse_spm_table.py captures/hitmv_table.txt [--all] [--since HH:MM:SS]
"""

import argparse
import collections
import re

ROW_START = re.compile(r"\r?\n(?=\d+\t\d\d/\d\d/\d{4} )")
CONFIG_IOCTLS = re.compile(
    r"SET_BAUD_RATE|SET_LINE_CONTROL|SET_HANDFLOW|SET_CHARS|SET_TIMEOUTS|SET_RTS|SET_DTR|"
    r"CLR_RTS|CLR_DTR|SET_QUEUE_SIZE|PURGE"
)


def iter_rows(path):
    """Yield rows as dicts.

    The monitor's redirected file sometimes contains stray line breaks *inside* a row,
    so rows are split only where a new row starts (`<number>\\t<dd/mm/yyyy>`); all other
    line breaks are dropped.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    header = None
    for chunk in ROW_START.split(text):
        cols = chunk.replace("\r", "").replace("\n", "").split("\t")
        if cols[0] == "#":
            header = cols
        elif header and len(cols) >= 6:
            yield dict(zip(header, cols))


def events(path):
    """Yield (time, kind, payload) with kind in TX, RX, CFG, PORT."""
    for row in iter_rows(path):
        func, direction, status = row["Function"], row["Direction"], row["Status"]
        data_hex = row.get("Data", "").strip()
        t = row["Time"]
        if func.startswith(("IRP_MJ_CREATE", "IRP_MJ_CLOSE")):
            if direction == "UP":
                yield t, "PORT", func
        elif CONFIG_IOCTLS.search(func):
            if direction == "DOWN":  # request parameters live on the DOWN row
                yield t, "CFG", f"{func.split('(')[-1].rstrip(')')} {data_hex}"
        elif direction == "UP" and status == "STATUS_SUCCESS" and data_hex:
            if func == "IRP_MJ_WRITE":
                yield t, "TX", bytes.fromhex(data_hex)
            elif func == "IRP_MJ_READ":
                yield t, "RX", bytes.fromhex(data_hex)


POLL_CMDS = {"Q:", "!:", "Q:S"}


def print_compact(out):
    """Print non-polling events verbatim; summarize each run of polling transactions."""
    run = []

    def flush():
        if not run:
            return
        by_cmd = collections.defaultdict(list)
        for _, (cmd, reply) in run:
            by_cmd[cmd].append(reply)
        parts = []
        for cmd, replies in by_cmd.items():
            first, last = replies[0], replies[-1]
            span = f"{first!r}" if first == last else f"{first!r} -> {last!r}"
            parts.append(f"{cmd} x{len(replies)} {span}")
        print(f"{run[0][0]} .. {run[-1][0].split()[-1]}  POLL  " + " | ".join(parts))
        run.clear()

    for t, kind, item in out:
        if kind == "XCHG" and item[0] in POLL_CMDS:
            run.append((t, item))
            continue
        flush()
        if kind == "XCHG":
            print(f"{t}  TX {item[0]!r:24} RX {item[1]!r}")
        elif kind == "PORT":
            print(f"{t}  {kind:4} {item}")
    flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--all", action="store_true", help="print every transaction, incl. polling")
    ap.add_argument("--since", help="only events at/after this time (HH:MM:SS)")
    ap.add_argument(
        "--compact", action="store_true",
        help="collapse runs of polling (Q:, !:, Q:S) into one summary line; hide CFG",
    )
    args = ap.parse_args()

    tx_buf, rx_buf = b"", b""
    pending = None
    out = []  # (time, kind, text) in order
    counts = collections.Counter()
    for t, kind, payload in events(args.path):
        if args.since and t.split()[-1] < args.since:
            continue
        if kind in ("CFG", "PORT"):
            out.append((t, kind, payload))
            continue
        if kind == "TX":
            tx_buf += payload
            while b"\r\n" in tx_buf:
                cmd, tx_buf = tx_buf.split(b"\r\n", 1)
                if pending:
                    out.append((pending[0], "XCHG", (pending[1], None)))
                pending = (t, cmd.decode("ascii", "replace"))
                counts[pending[1]] += 1
        else:
            rx_buf += payload
            while b"\r\n" in rx_buf:
                reply, rx_buf = rx_buf.split(b"\r\n", 1)
                reply = reply.decode("ascii", "replace")
                if pending:
                    out.append((pending[0], "XCHG", (pending[1], reply)))
                    pending = None
                elif reply:
                    out.append((t, "XCHG", (None, reply)))
    if pending:
        out.append((pending[0], "XCHG", (pending[1], None)))

    if args.compact:
        print_compact(out)
    else:
        last = None
        for t, kind, item in out:
            if kind == "XCHG":
                if args.all or item != last:
                    print(f"{t}  TX {item[0]!r:24} RX {item[1]!r}")
                last = item
            else:
                print(f"{t}  {kind:4} {item}")
                last = None
    print("\n--- command counts ---")
    for cmd, n in counts.most_common():
        print(f"{n:7}  {cmd!r}")


if __name__ == "__main__":
    main()
