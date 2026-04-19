from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)

from clubconcours.storage.repositories import RoundRepo


class RoundTab(QWidget):
    data_changed = Signal()

    COL_MATCH_ID = 0
    COL_TEAM1 = 1
    COL_SCORE1 = 2
    COL_SCORE2 = 3
    COL_TEAM2 = 4
    COL_STATUS = 5

    def __init__(self, conn: sqlite3.Connection, round_id: int) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)
        self.round_id = round_id

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.lbl_title = QLabel("")
        header.addWidget(self.lbl_title)

        header.addStretch(1)

        self.btn_save = QPushButton("Enregistrer scores")
        self.btn_save.clicked.connect(self.save_scores)
        header.addWidget(self.btn_save)

        self.btn_validate = QPushButton("Valider la partie")
        self.btn_validate.clicked.connect(self.validate_round)
        header.addWidget(self.btn_validate)

        layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Match ID", "Equipe A", "Score A", "Score B", "Equipe B", "Statut"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)

        self.refresh()

    def _team_label(self, team_id: int) -> str:
        rows = self.conn.execute(
            """
            SELECT p.name
            FROM round_team_players rtp
            JOIN players p ON p.id = rtp.player_id
            WHERE rtp.round_team_id=?
            ORDER BY p.name COLLATE NOCASE
            """,
            (team_id,),
        ).fetchall()
        names = [str(r["name"]) for r in rows]
        return ", ".join(names) if names else f"(team {team_id})"

    def refresh(self) -> None:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (self.round_id,)).fetchone()
        if r is None:
            self.lbl_title.setText(f"Round introuvable (id={self.round_id})")
            return

        title = f"Partie {r['number']}  |  format={r['format']}  |  mode={r['draw_mode']}"
        if int(r["validated"]) == 1:
            title += "  |  VALIDÉ"
        self.lbl_title.setText(title)

        matches = self.conn.execute(
            """
            SELECT id, team1_id, team2_id, score1, score2, validated
            FROM matches
            WHERE round_id=?
            ORDER BY id
            """,
            (self.round_id,),
        ).fetchall()

        self.table.setRowCount(0)

        for m in matches:
            row = self.table.rowCount()
            self.table.insertRow(row)

            match_id = int(m["id"])
            team1_id = int(m["team1_id"])
            team2_id = m["team2_id"]  # can be None

            team1_label = self._team_label(team1_id)
            team2_label = "EXEMPT" if team2_id is None else self._team_label(int(team2_id))

            # Match ID (read-only)
            it_id = QTableWidgetItem(str(match_id))
            it_id.setFlags(it_id.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_MATCH_ID, it_id)

            # Team labels (read-only)
            it_t1 = QTableWidgetItem(team1_label)
            it_t1.setFlags(it_t1.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TEAM1, it_t1)

            it_t2 = QTableWidgetItem(team2_label)
            it_t2.setFlags(it_t2.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TEAM2, it_t2)

            # Scores
            s1 = m["score1"]
            s2 = m["score2"]

            it_s1 = QTableWidgetItem("" if s1 is None else str(int(s1)))
            it_s2 = QTableWidgetItem("" if s2 is None else str(int(s2)))
            it_s1.setTextAlignment(Qt.AlignCenter)
            it_s2.setTextAlignment(Qt.AlignCenter)

            if team2_id is None or int(m["validated"]) == 1:
                # Exempt OR validated => read-only
                it_s1.setFlags(it_s1.flags() & ~Qt.ItemIsEditable)
                it_s2.setFlags(it_s2.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(row, self.COL_SCORE1, it_s1)
            self.table.setItem(row, self.COL_SCORE2, it_s2)

            # Status (read-only)
            status = "VALIDÉ" if int(m["validated"]) == 1 else "NON VALIDÉ"
            it_status = QTableWidgetItem(status)
            it_status.setFlags(it_status.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_STATUS, it_status)

        self.table.resizeColumnsToContents()

    def save_scores(self) -> None:
        # Load team2_id info (to skip exempts)
        match_info = self.conn.execute(
            "SELECT id, team2_id FROM matches WHERE round_id=?",
            (self.round_id,),
        ).fetchall()
        team2_by_match = {int(r["id"]): r["team2_id"] for r in match_info}

        try:
            for row in range(self.table.rowCount()):
                match_id = int(self.table.item(row, self.COL_MATCH_ID).text())
                if team2_by_match.get(match_id) is None:
                    continue  # exempt

                s1_txt = (self.table.item(row, self.COL_SCORE1).text() or "").strip()
                s2_txt = (self.table.item(row, self.COL_SCORE2).text() or "").strip()

                # Allow empty => NULL
                s1 = int(s1_txt) if s1_txt != "" else None
                s2 = int(s2_txt) if s2_txt != "" else None

                self.rr.set_match_score(match_id, s1, s2)

        except Exception as e:
            QMessageBox.critical(self, "Scores", f"Erreur enregistrement scores: {e}")
            return

        self.refresh()
        self.data_changed.emit()

    def validate_round(self) -> None:
        # Save first
        self.save_scores()
        try:
            self.rr.validate_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Validation", str(e))
            return

        QMessageBox.information(self, "Validation", "Partie validée (scores verrouillés).")
        self.refresh()
        self.data_changed.emit()