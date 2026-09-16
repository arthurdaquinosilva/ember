"""Session-aware input/output history stored in SQLite (IPython-compatible range syntax)."""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
import threading
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterator, NamedTuple

from prompt_toolkit.history import History

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session INTEGER PRIMARY KEY AUTOINCREMENT, start TIMESTAMP, end TIMESTAMP, num_cmds INTEGER, remark TEXT
);
CREATE TABLE IF NOT EXISTS history (
    session INTEGER, line INTEGER, source TEXT, source_raw TEXT, PRIMARY KEY (session, line)
);
CREATE TABLE IF NOT EXISTS output_history (
    session INTEGER, line INTEGER, output TEXT, PRIMARY KEY (session, line)
);
"""

# "4", "4-6", "4:6" (exclusive), "~1/", "~2/3-5", "7/1-4" (absolute session)
_RANGE = re.compile(r"^(?:(?P<sep>~?)(?P<session>\d+)/)?(?:(?P<start>\d+)?(?:(?P<op>[-:])(?P<end>\d+))?)$")


class Entry(NamedTuple):
    session: int
    line: int
    source: str
    output: str | None = None


class HistoryManager:
    def __init__(self, path: Path | str | None):
        self.path = str(path) if path else ":memory:"
        self._lock = threading.RLock()
        new = self.path == ":memory:" or not Path(self.path).exists()
        try:
            self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
            self.db.executescript(SCHEMA)
        except sqlite3.Error:
            self.path = ":memory:"
            self.db = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            self.db.executescript(SCHEMA)
        self.is_new = new
        self.session = self._new_session()

    # ── writing ───────────────────────────────────────────────────────────

    def _new_session(self) -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO sessions (start, num_cmds) VALUES (?, 0)", (dt.datetime.now().isoformat(),))
            return int(cur.lastrowid)

    def end_session(self) -> None:
        with self._lock:
            n = self.db.execute("SELECT COUNT(*) FROM history WHERE session = ?", (self.session,)).fetchone()[0]
            self.db.execute(
                "UPDATE sessions SET end = ?, num_cmds = ? WHERE session = ?",
                (dt.datetime.now().isoformat(), n, self.session),
            )

    def store_input(self, line: int, source: str, source_raw: str | None = None) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO history VALUES (?, ?, ?, ?)",
                (self.session, line, source, source_raw if source_raw is not None else source),
            )

    def store_output(self, line: int, output: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO output_history VALUES (?, ?, ?)", (self.session, line, output))

    def import_lines(self, lines: list[str], remark: str) -> None:
        with self._lock:
            cur = self.db.execute("INSERT INTO sessions (start, num_cmds, remark) VALUES (?, ?, ?)", (None, len(lines), remark))
            session = cur.lastrowid
            self.db.executemany(
                "INSERT INTO history VALUES (?, ?, ?, ?)", [(session, i, s, s) for i, s in enumerate(lines, 1)]
            )

    # ── reading ───────────────────────────────────────────────────────────

    def _rows(self, sql: str, params: tuple, raw: bool, output: bool) -> Iterator[Entry]:
        col = "source_raw" if raw else "source"
        if output:
            sql = sql.replace("SELECT session, line, {col}", "SELECT history.session, history.line, {col}, output")
            sql = sql.replace("FROM history", "FROM history LEFT JOIN output_history USING (session, line)")
        with self._lock:
            rows = self.db.execute(sql.format(col=col), params).fetchall()
        for row in rows:
            yield Entry(*row) if output else Entry(row[0], row[1], row[2])

    def get_range(self, session: int, start: int = 1, stop: int | None = None, raw: bool = True, output: bool = False) -> list[Entry]:
        """Lines [start, stop) of a session; `stop=None` means to the end."""
        sql = "SELECT session, line, {col} FROM history WHERE session = ? AND line >= ?"
        params: tuple = (session, start)
        if stop is not None:
            sql += " AND line < ?"
            params += (stop,)
        return list(self._rows(sql + " ORDER BY line", params, raw, output))

    def session_offset(self, offset: int) -> int | None:
        """Session id `offset` sessions before the current one (0 = current)."""
        with self._lock:
            rows = self.db.execute(
                "SELECT session FROM sessions WHERE session <= ? ORDER BY session DESC LIMIT 1 OFFSET ?",
                (self.session, offset),
            ).fetchall()
        return rows[0][0] if rows else None

    def get_range_by_str(self, spec: str, raw: bool = True, output: bool = False) -> list[Entry]:
        entries: list[Entry] = []
        for part in spec.split():
            m = _RANGE.match(part)
            if not m or not any(m.group(g) for g in ("session", "start", "end")):
                raise ValueError(f"bad history range {part!r}")
            if m["session"] is None:
                session = self.session
            elif m["sep"]:
                found = self.session_offset(int(m["session"]))
                if found is None:
                    raise ValueError(f"no session {part.split('/')[0]}")
                session = found
            else:
                session = int(m["session"])
            start = int(m["start"]) if m["start"] else 1
            if m["end"]:
                stop = int(m["end"]) + (1 if m["op"] == "-" else 0)
            elif m["start"]:
                stop = start + 1
            else:
                stop = None
            entries.extend(self.get_range(session, start, stop, raw, output))
        return entries

    def get_tail(self, n: int = 10, raw: bool = True, output: bool = False, include_latest: bool = False) -> list[Entry]:
        sql = "SELECT session, line, {col} FROM history ORDER BY session DESC, line DESC LIMIT ?"
        rows = list(self._rows(sql, (n + (0 if include_latest else 1),), raw, output))
        if not include_latest and rows and rows[0].session == self.session:
            rows = rows[1:]
        return list(reversed(rows[:n]))

    def search(self, pattern: str = "*", raw: bool = True, output: bool = False, n: int | None = None, unique: bool = False) -> list[Entry]:
        if "*" not in pattern and "?" not in pattern:
            pattern = f"*{pattern}*"
        sql = "SELECT session, line, {col} FROM history WHERE {col} GLOB ? ORDER BY session, line"
        rows = list(self._rows(sql, (pattern,), raw, output))
        if unique:
            seen: dict[str, Entry] = {}
            for row in rows:
                seen.pop(row.source, None)
                seen[row.source] = row
            rows = list(seen.values())
        return rows[-n:] if n else rows

    def recent_inputs(self, limit: int = 5000) -> list[str]:
        """Most recent first, de-duplicated — for prompt history navigation."""
        with self._lock:
            rows = self.db.execute(
                "SELECT source_raw FROM history ORDER BY session DESC, line DESC LIMIT ?", (limit * 2,)
            ).fetchall()
        seen: set[str] = set()
        out: list[str] = []
        for (src,) in rows:
            if src and src not in seen:
                seen.add(src)
                out.append(src)
                if len(out) >= limit:
                    break
        return out

    def sessions(self) -> list[tuple[int, str | None, str | None, int, str | None]]:
        with self._lock:
            return self.db.execute("SELECT session, start, end, num_cmds, remark FROM sessions ORDER BY session").fetchall()


class PromptHistory(History):
    """prompt_toolkit adapter: reads from SQLite; the shell does the writing."""

    def __init__(self, manager: HistoryManager):
        super().__init__()
        self.manager = manager

    def load_history_strings(self) -> Iterator[str]:
        yield from self.manager.recent_inputs()

    def store_string(self, string: str) -> None:
        pass


def glob_match(pattern: str, text: str) -> bool:
    return fnmatch(text, pattern if any(c in pattern for c in "*?") else f"*{pattern}*")
