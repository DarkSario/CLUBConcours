from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
)

from clubconcours.storage.repositories import RoundRepo


class ScoresTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Round:"))
        self.round_combo = QComboBox()
        top.addWidget(self.round_combo)

        self.btn_load = QPushButton("Charger")
        self.btn_load.clicked.connect(self._load)
        top.addWidget(self.btn_load)

        self.btn_validate = QPushButton("Valider la partie")
        self.btn_validate.clicked.connect(self._validate)
        top.addWidget(self.btn_validate)

        top.addStretch(1)
        layout.addLayout(top)

        self.info = QPlainTextEdit()
        self.info.setReadOnly(True)
        layout.addWidget(self.info)

        layout.addWidget(QLabel("Saisie scores (1 ligne = match_id score1 score2) :"))
        self.scores_edit = QPlainTextEdit()
        self.scores_edit.setPlaceholderText("5 13 9\n6 7 13\n...")
        layout.addWidget(self.scores_edit)

        row = QHBoxLayout()
        self.btn_save = QPushButton("Enregistrer scores")
        self.btn_save.clicked.connect(self._save_scores)
        row.addWidget(self.btn_save)
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self) -> None:
        self.round_combo.clear()
        rounds = self.conn.execute("SELECT id, number FROM rounds ORDER BY number").fetchall()
        for r in rounds:
            self.round_combo.addItem(f"Round {r['number']} (id={r['id']})", int(r["id"]))

    def _round_id(self) -> int | None:
        if self.round_combo.count() == 0:
            return None
        return int(self.round_combo.currentData())

    def _load(self) -> None:
        rid = self._round_id()
        if rid is None:
            return

        matches = self.conn.execute(
            """
            SELECT id, team1_id, team2_id, score1, score2
            FROM matches
            WHERE round_id=?
            ORDER BY id
            """,
            (rid,),
        ).fetchall()

        lines = []
        for m in matches:
            if m["team2_id"] is None:
                lines.append(f"match {m['id']}: EXEMPT score={m['score1']}-{m['score2']}")
            else:
                lines.append(f"match {m['id']}: score={m['score1']}-{m['score2']}")
        self.info.setPlainText("\n".join(lines))

    def _save_scores(self) -> None:
        rid = self._round_id()
        if rid is None:
            return

        raw = self.scores_edit.toPlainText().strip()
        if not raw:
            QMessageBox.information(self, "Scores", "Aucune ligne.")
            return

        try:
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                mid_s, s1_s, s2_s = line.split()
                mid = int(mid_s)
                s1 = int(s1_s)
                s2 = int(s2_s)
                self.rr.set_match_score(mid, s1, s2)
        except Exception as e:
            QMessageBox.critical(self, "Scores", f"Erreur saisie: {e}")
            return

        self._load()
        self.data_changed.emit()

    def _validate(self) -> None:
        rid = self._round_id()
        if rid is None:
            return
        try:
            self.rr.validate_round(rid)
        except Exception as e:
            QMessageBox.critical(self, "Validation", str(e))
            return

        QMessageBox.information(self, "Validation", "Partie validée (scores verrouillés).")
        self.data_changed.emit()