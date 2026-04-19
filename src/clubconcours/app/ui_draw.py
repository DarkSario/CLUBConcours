from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QMessageBox,
)

from clubconcours.core.draw import RoundConfig, draw_round
from clubconcours.storage.repositories import PlayerRepo


class DrawTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.player_repo = PlayerRepo(conn)

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["SINGLE", "DOUBLETTE", "TRIPLETTE"])
        row.addWidget(self.format_combo)

        row.addWidget(QLabel("Mode tirage:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["RANDOM", "AVOID_DUPLICATES", "SWISS_BY_WINS"])
        self.mode_combo.setCurrentText("AVOID_DUPLICATES")
        row.addWidget(self.mode_combo)

        self.btn_draw = QPushButton("Tirer la partie")
        self.btn_draw.clicked.connect(self._draw)
        row.addWidget(self.btn_draw)

        row.addStretch(1)
        layout.addLayout(row)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

    def refresh(self) -> None:
        # Nothing dynamic yet (we just show results when draw is clicked)
        pass

    def _next_round_number(self) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(number), 0) AS m FROM rounds").fetchone()
        return int(r["m"]) + 1

    def _draw(self) -> None:
        players = self.player_repo.list_players()
        if len(players) < 2:
            QMessageBox.warning(self, "Tirage", "Ajoute au moins 2 joueurs.")
            return

        round_number = self._next_round_number()
        fmt = self.format_combo.currentText()
        mode = self.mode_combo.currentText()

        try:
            round_id = draw_round(
                self.conn,
                round_number=round_number,
                cfg=RoundConfig(format=fmt, draw_mode=mode),
                player_ids=[p.id for p in players],
            )
        except Exception as e:
            QMessageBox.critical(self, "Tirage", str(e))
            return

        self.output.setPlainText(self._format_round(round_id))
        self.data_changed.emit()

    def _format_round(self, round_id: int) -> str:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
        lines = [f"Round {r['number']} (id={round_id}) format={r['format']} mode={r['draw_mode']}"]

        teams = self.conn.execute(
            """
            SELECT rt.id AS team_id, rt.team_index, p.name
            FROM round_teams rt
            JOIN round_team_players rtp ON rtp.round_team_id = rt.id
            JOIN players p ON p.id = rtp.player_id
            WHERE rt.round_id=?
            ORDER BY rt.team_index, p.name
            """,
            (round_id,),
        ).fetchall()

        team_map: dict[int, dict] = {}
        for row in teams:
            tid = int(row["team_id"])
            team_map.setdefault(tid, {"idx": int(row["team_index"]), "players": []})
            team_map[tid]["players"].append(str(row["name"]))

        lines.append("")
        for tid, info in sorted(team_map.items(), key=lambda kv: kv[1]["idx"]):
            lines.append(f"Team {info['idx']:>2}: {', '.join(info['players'])}")

        matches = self.conn.execute(
            """
            SELECT m.id, m.team1_id, m.team2_id, m.score1, m.score2
            FROM matches m
            WHERE m.round_id=?
            ORDER BY m.id
            """,
            (round_id,),
        ).fetchall()

        lines.append("")
        lines.append("Matchs:")
        for m in matches:
            t1 = int(m["team1_id"])
            t2 = m["team2_id"]
            s1 = m["score1"]
            s2 = m["score2"]

            if t2 is None:
                lines.append(f"- match {m['id']}: team {team_map[t1]['idx']} EXEMPT score={s1}-{s2}")
            else:
                lines.append(
                    f"- match {m['id']}: team {team_map[t1]['idx']} vs team {team_map[int(t2)]['idx']} score={s1}-{s2}"
                )

        return "\n".join(lines)