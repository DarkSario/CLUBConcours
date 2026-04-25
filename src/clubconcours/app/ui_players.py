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
    QCheckBox,
    QInputDialog,
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

        self._show_inactive = False

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

        self.chk_inactive = QCheckBox("Afficher joueurs inactifs")
        self.chk_inactive.stateChanged.connect(self._toggle_show_inactive)
        role_row.addStretch(1)
        role_row.addWidget(self.chk_inactive)
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

    def _toggle_show_inactive(self) -> None:
        self._show_inactive = self.chk_inactive.isChecked()
        self.refresh()

    def refresh(self) -> None:
        players_all = self.repo.list_players(active_only=False)
        players = players_all if self._show_inactive else [p for p in players_all if int(p.active) == 1]

        n = len(players_all)
        n_active = sum(1 for p in players_all if int(p.active) == 1)
        n_inactive = n - n_active
        n_t = sum(1 for p in players_all if p.role == "TIREUR" and int(p.active) == 1)
        n_p = sum(1 for p in players_all if p.role == "PLACEUR" and int(p.active) == 1)
        n_m = sum(1 for p in players_all if p.role == "MIXTE" and int(p.active) == 1)

        self.lbl_dash.setText(
            f"Joueurs: {n_active} actifs (+{n_inactive} inactifs)  |  Tireurs: {n_t}  |  Placeurs: {n_p}  |  Mixtes: {n_m}"
        )

        self.list_widget.clear()
        for p in players:
            status = "" if int(p.active) == 1 else " [INACTIF]"
            self.list_widget.addItem(f"{p.id} - {p.name} ({ROLE_LABELS.get(p.role, p.role)}){status}")

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
        self.refresh()

    def _selected_player_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        txt = item.text()
        try:
            left = txt.split("-", 1)[0].strip()
            return int(left)
        except Exception:
            return None

    def _get_player_row(self, player_id: int):
        rows = self.repo.list_players(active_only=False)
        for p in rows:
            if p.id == player_id:
                return p
        return None

    def _context_menu(self, pos: QPoint) -> None:
        pid = self._selected_player_id()
        if pid is None:
            return

        p = self._get_player_row(pid)
        if p is None:
            return

        menu = QMenu(self)

        act_rename = menu.addAction("Renommer…")

        menu.addSeparator()

        sub = menu.addMenu("Changer rôle")
        actions_role = {}
        for r in PLAYER_ROLES:
            a = sub.addAction(ROLE_LABELS.get(r, r))
            actions_role[a] = r

        menu.addSeparator()

        if int(p.active) == 1:
            act_deactivate = menu.addAction("Désactiver (abandon/blessure)")
            act_reactivate = None
        else:
            act_deactivate = None
            act_reactivate = menu.addAction("Réactiver")

        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen is None:
            return

        if chosen is act_rename:
            new_name, ok = QInputDialog.getText(self, "Renommer joueur", "Nouveau nom :", text=p.name)
            if not ok:
                return
            try:
                self.repo.rename_player(pid, new_name)
            except Exception as e:
                QMessageBox.critical(self, "Renommer", str(e))
                return
            self.data_changed.emit()
            self.refresh()
            return

        if chosen in actions_role:
            try:
                self.repo.set_player_role(pid, actions_role[chosen])
            except Exception as e:
                QMessageBox.critical(self, "Rôle", str(e))
                return
            self.data_changed.emit()
            self.refresh()
            return

        if act_deactivate is not None and chosen is act_deactivate:
            ok = QMessageBox.question(
                self,
                "Désactiver",
                f"Désactiver {p.name} ?\n\nIl/elle ne sera plus tiré(e) à partir de la prochaine partie.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ok != QMessageBox.Yes:
                return
            try:
                self.repo.set_player_active(pid, False)
            except Exception as e:
                QMessageBox.critical(self, "Désactiver", str(e))
                return
            self.data_changed.emit()
            self.refresh()
            return

        if act_reactivate is not None and chosen is act_reactivate:
            try:
                self.repo.set_player_active(pid, True)
            except Exception as e:
                QMessageBox.critical(self, "Réactiver", str(e))
                return
            self.data_changed.emit()
            self.refresh()
            return