from __future__ import annotations

import sqlite3
from typing import Optional

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPushButton,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)

from clubconcours.storage.repositories import RoundRepo


class ScoresTab(QWidget):
    data_changed = Signal()

    COL_MATCH_ID = 0
    COL_TEAM1 = 1
    COL_SCORE1 = 2
    COL_SCORE2 = 3
    COL_TEAM2 = 4
    COL_STATUS = 5

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)

        self._current_round_id: Optional[int] = None

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Round:"))
        self.round_combo = QComboBox()
        top.addWidget(self.round_combo)

        self.btn_load = QPushButton("Charger")
        self.btn_load.clicked.connect(self._load)
        top.addWidget(self.btn_load)

        self.btn_save = QPushButton("Enregistrer scores")
        self.btn_save.clicked.connect(self._save_scores)
        top.addWidget(self.btn_save)

        self.btn_validate = QPushButton("Valider la partie")
        self.btn_validate.clicked.connect(self._validate)
        top.addWidget(self.btn_validate)

        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Match ID", "Equipe A", "Score A", "Score B", "Equipe B", "Statut"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        current = self._current_round_id

        self.round_combo.clear()
        rounds = self.conn.execute(
            "SELECT id, number FROM rounds ORDER BY number"
        ).fetchall()
        for r in rounds:
            rid = int(r["id"])
            self.round_combo.addItem(f"Round {r['number']} (id={rid})", rid)

        # restore selection if possible
        if current is not None:
            idx = self.round_combo.findData(current)
            if idx >= 0:
                self.round_combo.setCurrentIndex(idx)

    def _round_id(self) -> Optional[int]:
        if self.round_combo.count() == 0:
            return None
        return int(self.round_combo.currentData())

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

    def _load(self) -> None:
        rid = self._round_id()
        self._current_round_id = rid
        if rid is None:
            return

        matches = self.conn.execute(
            """
            SELECT id, team1_id, team2_id, score1, score2, validated
            FROM matches
            WHERE round_id=?
            ORDER BY id
            """,
            (rid,),
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

            if team2_id is None:
                # Exempt: read-only (prefilled by draw if configured)
                it_s1.setFlags(it_s1.flags() & ~Qt.ItemIsEditable)
                it_s2.setFlags(it_s2.flags() & ~Qt.ItemIsEditable)
            else:
                # normal match: allow editing
                it_s1.setTextAlignment(Qt.AlignCenter)
                it_s2.setTextAlignment(Qt.AlignCenter)

            self.table.setItem(row, self.COL_SCORE1, it_s1)
            self.table.setItem(row, self.COL_SCORE2, it_s2)

            # Status (read-only)
            status = "VALIDÉ" if int(m["validated"]) == 1 else "NON VALIDÉ"
            it_status = QTableWidgetItem(status)
            it_status.setFlags(it_status.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_STATUS, it_status)

        self.table.resizeColumnsToContents()

    def _save_scores(self) -> None:
        rid = self._current_round_id
        if rid is None:
            rid = self._round_id()
            self._current_round_id = rid
        if rid is None:
            return

        # Load team2_id info (to skip exempts)
        match_info = self.conn.execute(
            "SELECT id, team2_id FROM matches WHERE round_id=?",
            (rid,),
        ).fetchall()
        team2_by_match = {int(r["id"]): r["team2_id"] for r in match_info}

        try:
            for row in range(self.table.rowCount()):
                match_id = int(self.table.item(row, self.COL_MATCH_ID).text())
                if team2_by_match.get(match_id) is None:
                    continue  # exempt -> don't touch

                s1_txt = (self.table.item(row, self.COL_SCORE1).text() or "").strip()
                s2_txt = (self.table.item(row, self.COL_SCORE2).text() or "").strip()

                # Allow leaving empty => store NULLs (but validation will refuse)
                s1 = int(s1_txt) if s1_txt != "" else None
                s2 = int(s2_txt) if s2_txt != "" else None

                self.rr.set_match_score(match_id, s1, s2)

        except Exception as e:
            QMessageBox.critical(self, "Scores", f"Erreur enregistrement scores: {e}")
            return

        QMessageBox.information(self, "Scores", "Scores enregistrés.")
        self._load()
        self.data_changed.emit()

    def _validate(self) -> None:
        rid = self._current_round_id
        if rid is None:
            rid = self._round_id()
            self._current_round_id = rid
        if rid is None:
            return

        # Save first so user doesn't forget
        self._save_scores()

        try:
            self.rr.validate_round(rid)
        except Exception as e:
            QMessageBox.critical(self, "Validation", str(e))
            return

        QMessageBox.information(self, "Validation", "Partie validée (scores verrouillés).")
        self._load()
        self.data_changed.emit()