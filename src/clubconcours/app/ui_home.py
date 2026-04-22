from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame


class HomeTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

        layout = QVBoxLayout(self)

        # Dashboard card
        self.card = QFrame()
        self.card.setFrameShape(QFrame.StyledPanel)
        self.card.setStyleSheet("QFrame { background:#0B1220; border:1px solid #1F2937; border-radius:10px; }")
        card_l = QVBoxLayout(self.card)

        self.title = QLabel("Accueil")
        self.title.setStyleSheet("font-weight:700; font-size: 18px;")
        card_l.addWidget(self.title)

        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet("color:#9CA3AF;")
        card_l.addWidget(self.subtitle)

        self.stats = QLabel("")
        self.stats.setStyleSheet("color:#9CA3AF;")
        card_l.addWidget(self.stats)

        layout.addWidget(self.card)

        # Quick actions
        btn_row = QHBoxLayout()

        self.btn_go_current = QPushButton("Aller à la partie en cours")
        btn_row.addWidget(self.btn_go_current)

        self.btn_draw_next = QPushButton("Tirer la prochaine partie")
        btn_row.addWidget(self.btn_draw_next)

        self.btn_export_ranking = QPushButton("Exporter classement PDF…")
        btn_row.addWidget(self.btn_export_ranking)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addStretch(1)
        self.refresh()

    def _meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def refresh(self) -> None:
        name = self._meta_get("tournament_name") or "CLUBConcours"
        d = self._meta_get("tournament_date") or ""
        loc = self._meta_get("tournament_location") or ""
        sub = " — ".join([x for x in [d, loc] if x])

        planned = self._meta_get("num_rounds_planned") or "?"
        init = self._meta_get("contest_initialized") == "1"

        n_players = int(self.conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()["n"])
        n_rounds = int(self.conn.execute("SELECT COUNT(*) AS n FROM rounds").fetchone()["n"])
        n_validated = int(self.conn.execute("SELECT COUNT(*) AS n FROM matches WHERE validated=1").fetchone()["n"])

        prog = self.conn.execute(
            """
            SELECT
              SUM(CASE WHEN team2_id IS NOT NULL THEN 1 ELSE 0 END) AS n_played,
              SUM(CASE WHEN team2_id IS NOT NULL AND score1 IS NOT NULL AND score2 IS NOT NULL THEN 1 ELSE 0 END) AS n_scored
            FROM matches
            """
        ).fetchone()
        n_played = int(prog["n_played"] or 0)
        n_scored = int(prog["n_scored"] or 0)

        cur_round = int(self.conn.execute("SELECT COALESCE(MAX(number), 0) AS m FROM rounds").fetchone()["m"])

        self.title.setText(name)
        self.subtitle.setText(sub if sub else " ")
        self.stats.setText(
            f"Concours: {'OK' if init else 'NON'}  |  Joueurs: {n_players}  |  "
            f"Parties: {n_rounds}/{planned}  |  Partie en cours: {cur_round}  |  "
            f"Scores saisis: {n_scored}/{n_played}  |  Matchs validés: {n_validated}"
        )