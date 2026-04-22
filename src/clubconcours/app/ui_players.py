from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QListWidget,
    QMessageBox,
    QFrame,
)

from clubconcours.storage.repositories import PlayerRepo


class PlayersTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.repo = PlayerRepo(conn)

        layout = QVBoxLayout(self)

        # Dashboard
        self.card = QFrame()
        self.card.setFrameShape(QFrame.StyledPanel)
        self.card.setStyleSheet("QFrame { background:#0B1220; border:1px solid #1F2937; border-radius:10px; }")
        card_l = QHBoxLayout(self.card)
        self.lbl_dash = QLabel("")
        self.lbl_dash.setStyleSheet("color:#9CA3AF;")
        card_l.addWidget(self.lbl_dash)
        card_l.addStretch(1)
        layout.addWidget(self.card)

        layout.addWidget(QLabel("Ajouter des joueurs (1 nom par ligne) :"))
        self.names_edit = QTextEdit()
        self.names_edit.setPlaceholderText("Alice\nBob\nChloé\n...")
        layout.addWidget(self.names_edit)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Enregistrer joueurs")
        self.btn_add.setProperty("primary", True)
        self.btn_add.setToolTip("Ajoute les joueurs saisis (1 par ligne)")
        self.btn_add.clicked.connect(self._add_players)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Liste joueurs :"))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        self.refresh()

    def refresh(self) -> None:
        players = self.repo.list_players()
        self.lbl_dash.setText(f"Joueurs inscrits: {len(players)}")
        self.list_widget.clear()
        for p in players:
            self.list_widget.addItem(f"{p.id} - {p.name}")

    def _add_players(self) -> None:
        raw = self.names_edit.toPlainText()
        names = [line.strip() for line in raw.splitlines() if line.strip()]
        if not names:
            QMessageBox.information(self, "Joueurs", "Aucun nom à ajouter.")
            return
        self.repo.add_players(names)
        self.names_edit.clear()
        self.data_changed.emit()