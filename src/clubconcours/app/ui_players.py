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
)

from clubconcours.storage.repositories import PlayerRepo


class PlayersTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.repo = PlayerRepo(conn)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Ajouter des joueurs (1 nom par ligne) :"))
        self.names_edit = QTextEdit()
        self.names_edit.setPlaceholderText("Alice\nBob\nChloé\n...")
        layout.addWidget(self.names_edit)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Enregistrer joueurs")
        self.btn_add.clicked.connect(self._add_players)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Liste joueurs :"))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

    def refresh(self) -> None:
        self.list_widget.clear()
        for p in self.repo.list_players():
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