from __future__ import annotations

import sqlite3

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
    COL_TERRAIN = 1
    COL_TEAM1 = 2
    COL_SCORE1 = 3
    COL_SCORE2 = 4
    COL_TEAM2 = 5
    COL_STATUS = 6

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

        self.btn_assign = QPushButton("Retirer terrains")
        self.btn_assign.clicked.connect(self.assign_courts)
        header.addWidget(self.btn_assign)

        self.btn_save = QPushButton("Enregistrer scores")
        self.btn_save.clicked.connect(self.save_scores)
        header.addWidget(self.btn_save)

        self.btn_validate = QPushButton("Valider la partie")
        self.btn_validate.clicked.connect(self.validate_round)
        header.addWidget(self.btn_validate)

        self.btn_unlock = QPushButton("Déverrouiller")
        self.btn_unlock.clicked.connect(self.unlock_round)
        header.addWidget(self.btn_unlock)

        layout.addLayout(header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Match ID", "Terrain", "Equipe A", "Score A", "Score B", "Equipe B", "Statut"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)

        self.refresh()

    def _is_locked(self) -> bool:
        r = self.conn.execute(
            "SELECT scores_locked, validated FROM rounds WHERE id=?",
            (self.round_id,),
        ).fetchone()
        if r is None:
            return False
        return int(r["scores_locked"]) == 1 or int(r["validated"]) == 1

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
        return ", ".join(str(r["name"]) for r in rows)

    def refresh(self) -> None:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (self.round_id,)).fetchone()
        if r is None:
            self.lbl_title.setText(f"Round introuvable (id={self.round_id})")
            return

        locked = self._is_locked()
        title = f"Partie {r['number']}  |  format={r['format']}  |  mode={r['draw_mode']}"
        if locked:
            title += "  |  VERROUILLÉ"
        self.lbl_title.setText(title)

        matches = self.conn.execute(
            """
            SELECT m.id, m.team1_id, m.team2_id, m.score1, m.score2, m.validated,
                   ca.court_number AS court_number
            FROM matches m
            LEFT JOIN court_assignments ca ON ca.match_id = m.id
            WHERE m.round_id=?
            ORDER BY m.id
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

            # Match ID
            it_id = QTableWidgetItem(str(match_id))
            it_id.setFlags(it_id.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_MATCH_ID, it_id)

            # Terrain
            court = m["court_number"]
            it_court = QTableWidgetItem("" if court is None else str(int(court)))
            it_court.setTextAlignment(Qt.AlignCenter)
            it_court.setFlags(it_court.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TERRAIN, it_court)

            # Teams
            t1 = QTableWidgetItem(self._team_label(team1_id))
            t1.setFlags(t1.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TEAM1, t1)

            if team2_id is None:
                t2_label = "EXEMPT"
            else:
                t2_label = self._team_label(int(team2_id))
            t2 = QTableWidgetItem(t2_label)
            t2.setFlags(t2.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TEAM2, t2)

            # Scores
            s1 = m["score1"]
            s2 = m["score2"]
            it_s1 = QTableWidgetItem("" if s1 is None else str(int(s1)))
            it_s2 = QTableWidgetItem("" if s2 is None else str(int(s2)))
            it_s1.setTextAlignment(Qt.AlignCenter)
            it_s2.setTextAlignment(Qt.AlignCenter)

            if locked or team2_id is None:
                it_s1.setFlags(it_s1.flags() & ~Qt.ItemIsEditable)
                it_s2.setFlags(it_s2.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(row, self.COL_SCORE1, it_s1)
            self.table.setItem(row, self.COL_SCORE2, it_s2)

            # Status
            status = "VALIDÉ" if int(m["validated"]) == 1 else "NON VALIDÉ"
            it_status = QTableWidgetItem(status)
            it_status.setFlags(it_status.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_STATUS, it_status)

        self.table.resizeColumnsToContents()

        self.btn_save.setEnabled(not locked)
        self.btn_validate.setEnabled(not locked)
        self.btn_assign.setEnabled(not locked)
        self.btn_unlock.setEnabled(locked)

    def save_scores(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Scores", "Partie verrouillée.")
            return

        team2_by_match = {
            int(r["id"]): r["team2_id"]
            for r in self.conn.execute(
                "SELECT id, team2_id FROM matches WHERE round_id=?",
                (self.round_id,),
            ).fetchall()
        }

        try:
            for row in range(self.table.rowCount()):
                match_id = int(self.table.item(row, self.COL_MATCH_ID).text())
                if team2_by_match.get(match_id) is None:
                    continue  # exempt

                s1_txt = (self.table.item(row, self.COL_SCORE1).text() or "").strip()
                s2_txt = (self.table.item(row, self.COL_SCORE2).text() or "").strip()

                s1 = int(s1_txt) if s1_txt != "" else None
                s2 = int(s2_txt) if s2_txt != "" else None

                self.rr.set_match_score(match_id, s1, s2)

        except Exception as e:
            QMessageBox.critical(self, "Scores", f"Erreur enregistrement scores: {e}")
            return

        self.refresh()
        self.data_changed.emit()

    def assign_courts(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Terrains", "Partie verrouillée.")
            return
        try:
            self.rr.assign_courts_for_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Terrains", str(e))
            return
        self.refresh()
        self.data_changed.emit()

    def validate_round(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Validation", "Partie déjà verrouillée.")
            return

        self.save_scores()
        try:
            self.rr.validate_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Validation", str(e))
            return

        QMessageBox.information(self, "Validation", "Partie validée (scores + terrains verrouillés).")
        self.refresh()
        self.data_changed.emit()

    def unlock_round(self) -> None:
        if not self._is_locked():
            return

        ok = QMessageBox.question(
            self,
            "Déverrouiller",
            "Déverrouiller cette partie ?\n"
            "Cela permettra de modifier les scores et les terrains.\n\n"
            "Confirmer ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return

        try:
            self.rr.unlock_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Déverrouiller", str(e))
            return

        self.refresh()
        self.data_changed.emit()