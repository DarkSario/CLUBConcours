from __future__ import annotations

import sqlite3

from PySide6.QtCore import Signal, Qt, QPoint
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
    QComboBox,
    QMenu,
)

from clubconcours.storage.repositories import PlayerRepo, PLAYER_ROLES


ROLE_LABELS = {
    "TIREUR": "Tireur",
    "PLACEUR": "Placeur",
    "MIXTE": "Mixte",
}


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

        role_row = QHBoxLayout()
        role_row.addWidget(QLabel("Rôle des joueurs ajoutés:"))
        self.role_combo = QComboBox()
        for r in PLAYER_ROLES:
            self.role_combo.addItem(ROLE_LABELS.get(r, r), r)
        self.role_combo.setCurrentIndex(self.role_combo.findData("MIXTE"))
        role_row.addWidget(self.role_combo)
        role_row.addStretch(1)
        layout.addLayout(role_row)

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
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.list_widget)

        self.refresh()

    def refresh(self) -> None:
        players = self.repo.list_players()
        n = len(players)
        n_t = sum(1 for p in players if p.role == "TIREUR")
        n_p = sum(1 for p in players if p.role == "PLACEUR")
        n_m = sum(1 for p in players if p.role == "MIXTE")
        self.lbl_dash.setText(f"Joueurs: {n}  |  Tireurs: {n_t}  |  Placeurs: {n_p}  |  Mixtes: {n_m}")

        self.list_widget.clear()
        for p in players:
            self.list_widget.addItem(f"{p.id} - {p.name} ({ROLE_LABELS.get(p.role, p.role)})")

    def _add_players(self) -> None:
        raw = self.names_edit.toPlainText()
        names = [line.strip() for line in raw.splitlines() if line.strip()]
        if not names:
            QMessageBox.information(self, "Joueurs", "Aucun nom à ajouter.")
            return

        role = self.role_combo.currentData() or "MIXTE"
        self.repo.add_players(names, role=str(role))

        self.names_edit.clear()
        self.data_changed.emit()

    def _selected_player_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        txt = item.text()
        # "12 - Alice (Tireur)"
        try:
            left = txt.split("-", 1)[0].strip()
            return int(left)
        except Exception:
            return None

    def _context_menu(self, pos: QPoint) -> None:
        pid = self._selected_player_id()
        if pid is None:
            return

        menu = QMenu(self)
        sub = menu.addMenu("Changer rôle")
        actions = {}
        for r in PLAYER_ROLES:
            a = sub.addAction(ROLE_LABELS.get(r, r))
            actions[a] = r

        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen in actions:
            try:
                self.repo.set_player_role(pid, actions[chosen])
            except Exception as e:
                QMessageBox.critical(self, "Rôle", str(e))
                return
            self.data_changed.emit()
            self.refresh()