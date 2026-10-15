"""Durable Discord resource IDs, ticket reservations, and order records.

SQLite lives outside the source tree by default. All SQL values are bound, and
active-ticket uniqueness is enforced in the database as well as in the UI.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = ("creating", "open", "closing")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS resources (
                kind TEXT NOT NULL, key TEXT NOT NULL, discord_id INTEGER NOT NULL,
                PRIMARY KEY (kind, key)
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                product_id TEXT NOT NULL, product_name TEXT NOT NULL,
                channel_id INTEGER UNIQUE, control_message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'creating'
                  CHECK(status IN ('creating','open','closing','closed','failed')),
                quantity TEXT NOT NULL, server TEXT NOT NULL, details TEXT NOT NULL,
                claimed_by INTEGER, created_at REAL NOT NULL,
                completed_at REAL, closed_at REAL, transcript_path TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS unique_active_ticket
                ON tickets(guild_id, user_id, product_id)
                WHERE status IN ('creating','open','closing');
            CREATE TABLE IF NOT EXISTS orders (
                ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
                guild_id INTEGER NOT NULL, customer_id INTEGER NOT NULL,
                product_id TEXT NOT NULL, quantity TEXT NOT NULL,
                server TEXT NOT NULL, details TEXT NOT NULL,
                completed_by INTEGER NOT NULL, completed_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tickets_owner
                ON tickets(guild_id, user_id, status);
            """
        )
        self.db.commit()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass  # Windows ACLs are inherited from the chosen data directory.

    def get_resource(self, kind: str, key: str) -> int | None:
        row = self.db.execute(
            "SELECT discord_id FROM resources WHERE kind=? AND key=?", (kind, key)
        ).fetchone()
        return int(row[0]) if row else None

    def set_resource(self, kind: str, key: str, discord_id: int) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO resources(kind,key,discord_id) VALUES(?,?,?) "
                "ON CONFLICT(kind,key) DO UPDATE SET discord_id=excluded.discord_id",
                (kind, key, int(discord_id)),
            )

    def delete_resource(self, kind: str, key: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM resources WHERE kind=? AND key=?", (kind, key))

    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    def ticket_by_channel(self, channel_id: int) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM tickets WHERE channel_id=?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None

    def active_ticket(self, guild_id: int, user_id: int, product_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM tickets WHERE guild_id=? AND user_id=? AND product_id=? "
            "AND status IN ('creating','open','closing')",
            (guild_id, user_id, product_id),
        ).fetchone()
        return dict(row) if row else None

    def active_tickets(self, guild_id: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tickets WHERE status IN ('creating','open','closing')"
        args: tuple = ()
        if guild_id is not None:
            sql += " AND guild_id=?"
            args = (guild_id,)
        return [dict(row) for row in self.db.execute(sql + " ORDER BY id", args)]

    def count_active(self, guild_id: int, user_id: int) -> int:
        return int(self.db.execute(
            "SELECT COUNT(*) FROM tickets WHERE guild_id=? AND user_id=? "
            "AND status IN ('creating','open','closing')", (guild_id, user_id)
        ).fetchone()[0])

    def last_created(self, guild_id: int, user_id: int) -> float | None:
        row = self.db.execute(
            "SELECT MAX(created_at) FROM tickets WHERE guild_id=? AND user_id=? "
            "AND status != 'failed'", (guild_id, user_id)
        ).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    def reserve_ticket(self, *, guild_id: int, user_id: int, product_id: str,
                       product_name: str, quantity: str, server: str,
                       details: str) -> dict[str, Any]:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO tickets(guild_id,user_id,product_id,product_name,quantity,"
                "server,details,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (guild_id, user_id, product_id, product_name, quantity, server, details, time.time()),
            )
        return self.get_ticket(int(cursor.lastrowid))  # type: ignore[return-value]

    def update_ticket(self, ticket_id: int, **changes: Any) -> None:
        allowed = {"channel_id", "control_message_id", "status", "claimed_by",
                   "completed_at", "closed_at", "transcript_path"}
        if not changes or set(changes) - allowed:
            raise ValueError("Unsupported ticket update")
        columns = ",".join(f"{key}=?" for key in changes)
        with self.db:
            self.db.execute(f"UPDATE tickets SET {columns} WHERE id=?",
                            (*changes.values(), ticket_id))

    def complete_ticket(self, ticket_id: int, staff_id: int) -> bool:
        now = time.time()
        with self.db:
            # The conditional write obtains SQLite's write lock before reading.
            # Two callbacks/connections cannot record the same order twice.
            updated = self.db.execute(
                "UPDATE tickets SET completed_at=? WHERE id=? AND status='open' "
                "AND completed_at IS NULL", (now, ticket_id),
            )
            if updated.rowcount != 1:
                return False
            ticket = self.get_ticket(ticket_id)
            self.db.execute(
                "INSERT INTO orders(ticket_id,guild_id,customer_id,product_id,quantity,"
                "server,details,completed_by,completed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (ticket_id, ticket["guild_id"], ticket["user_id"], ticket["product_id"],
                 ticket["quantity"], ticket["server"], ticket["details"], staff_id, now),
            )
        return True

    def claim_ticket(self, ticket_id: int, staff_id: int) -> bool:
        with self.db:
            updated = self.db.execute(
                "UPDATE tickets SET claimed_by=? WHERE id=? AND status='open' "
                "AND claimed_by IS NULL", (staff_id, ticket_id),
            )
        return updated.rowcount == 1

    def recent_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM orders ORDER BY completed_at DESC LIMIT ?", (max(1, min(limit, 100)),)
        )]

    def close(self) -> None:
        self.db.close()
