from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QMessageBox,
)

from clubconcours.storage.repositories import RoundRepo

FORMATS = ["SINGLE", "DOUBLETTE", "TRIPLETTE"]

DRAW_MODE_LABELS: dict[str, str] = {
    "RANDOM": "Aléatoire",
    "AVOID_DUPLICATES": "Éviter les doublons",
    "SWISS_BY_WINS": "Suisse (par victoires)",
}

DRAW_MODE_HELP: dict[str, str] = {
    "RANDOM": "Tirage totalement aléatoire (aucune contrainte).",
    "AVOID_DUPLICATES": "Essaye d’éviter que des joueurs rejouent ensemble trop souvent.",
    "SWISS_BY_WINS": "Regroupe les joueurs selon le nombre de victoires (niveau similaire).",
}

MODES = ["AVOID_DUPLICATES", "SWISS_BY_WINS", "RANDOM"]


class ConcoursTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Paramètres concours"))
        header.addStretch(1)

        self.btn_save = QPushButton("Sauvegarder")
        self.btn_save.clicked.connect(self._save)
        header.addWidget(self.btn_save)

        layout.addLayout(header)

        row = QHBoxLayout()
        row.addWidget(QLabel("Nombre de terrains:"))
        self.spin_courts = QSpinBox()
        self.spin_courts.setMinimum(1)
        self.spin_courts.setMaximum(999)
        self.spin_courts.setValue(12)
        row.addWidget(self.spin_courts)

        row.addWidget(QLabel("Nombre de parties:"))
        self.spin_rounds = QSpinBox()
        self.spin_rounds.setMinimum(1)
        self.spin_rounds.setMaximum(50)
        self.spin_rounds.setValue(4)
        self.spin_rounds.valueChanged.connect(self._resize_plan_table)
        row.addWidget(self.spin_rounds)

        row.addStretch(1)
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Partie", "Format", "Mode tirage"])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)

        self.mode_help = QLabel("")
        self.mode_help.setStyleSheet("color: #666;")
        layout.addWidget(self.mode_help)

        self.refresh()

    def _meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _populate_mode_combo(self, combo: QComboBox) -> None:
        combo.clear()
        for code in MODES:
            combo.addItem(DRAW_MODE_LABELS.get(code, code), code)
            combo.setItemData(combo.count() - 1, DRAW_MODE_HELP.get(code, ""), role=Qt.ToolTipRole)

    def _mode_code_from_combo(self, combo: QComboBox) -> str:
        code = combo.currentData()
        return str(code) if code else "AVOID_DUPLICATES"

    def _set_mode_combo_by_code(self, combo: QComboBox, code: str) -> None:
        idx = combo.findData(code)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _update_mode_help(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            row = 0 if self.table.rowCount() > 0 else -1

        if row >= 0:
            cb_mode = self.table.cellWidget(row, 2)
            if isinstance(cb_mode, QComboBox):
                code = self._mode_code_from_combo(cb_mode)
                self.mode_help.setText(f"Explication : {DRAW_MODE_HELP.get(code, '')}")
                return
        self.mode_help.setText("")

    def refresh(self) -> None:
        num_courts = self._meta_get("num_courts")
        if num_courts is not None:
            try:
                self.spin_courts.setValue(int(num_courts))
            except Exception:
                pass

        planned = self._meta_get("num_rounds_planned")
        if planned is not None:
            try:
                self.spin_rounds.setValue(int(planned))
            except Exception:
                pass

        plan_json = self._meta_get("round_plan_json")
        plan: list[dict] = []
        if plan_json:
            try:
                plan = json.loads(plan_json)
            except Exception:
                plan = []

        self._resize_plan_table()

        for i in range(self.table.rowCount()):
            fmt = "DOUBLETTE"
            mode = "AVOID_DUPLICATES"
            if i < len(plan):
                fmt = plan[i].get("format", fmt)
                mode = plan[i].get("draw_mode", mode)

            it_num = QTableWidgetItem(str(i + 1))
            it_num.setFlags(it_num.flags() & ~Qt.ItemIsEditable)
            it_num.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, it_num)

            cb_fmt = self.table.cellWidget(i, 1)
            if isinstance(cb_fmt, QComboBox):
                cb_fmt.setCurrentText(fmt if fmt in FORMATS else "DOUBLETTE")

            cb_mode = self.table.cellWidget(i, 2)
            if isinstance(cb_mode, QComboBox):
                self._set_mode_combo_by_code(cb_mode, mode if mode in MODES else "AVOID_DUPLICATES")

        self.table.resizeColumnsToContents()
        self._update_mode_help()

    def _resize_plan_table(self) -> None:
        n = int(self.spin_rounds.value())
        self.table.setRowCount(n)

        for i in range(n):
            it_num = QTableWidgetItem(str(i + 1))
            it_num.setFlags(it_num.flags() & ~Qt.ItemIsEditable)
            it_num.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, it_num)

            cb_fmt = self.table.cellWidget(i, 1)
            if not isinstance(cb_fmt, QComboBox):
                cb_fmt = QComboBox()
                cb_fmt.addItems(FORMATS)
                cb_fmt.setCurrentText("DOUBLETTE")
                self.table.setCellWidget(i, 1, cb_fmt)

            cb_mode = self.table.cellWidget(i, 2)
            if not isinstance(cb_mode, QComboBox):
                cb_mode = QComboBox()
                self._populate_mode_combo(cb_mode)
                self._set_mode_combo_by_code(cb_mode, "AVOID_DUPLICATES")
                cb_mode.currentIndexChanged.connect(self._update_mode_help)
                self.table.setCellWidget(i, 2, cb_mode)

        self.table.currentCellChanged.connect(lambda *_: self._update_mode_help())
        self.table.resizeColumnsToContents()
        self._update_mode_help()

    def _save(self) -> None:
        self._resize_plan_table()

        try:
            self.rr.set_num_courts(int(self.spin_courts.value()))
            planned = int(self.spin_rounds.value())

            plan: list[dict] = []
            for i in range(self.table.rowCount()):
                cb_fmt = self.table.cellWidget(i, 1)
                cb_mode = self.table.cellWidget(i, 2)
                fmt = cb_fmt.currentText() if isinstance(cb_fmt, QComboBox) else "DOUBLETTE"
                mode = self._mode_code_from_combo(cb_mode) if isinstance(cb_mode, QComboBox) else "AVOID_DUPLICATES"
                plan.append({"round_number": i + 1, "format": fmt, "draw_mode": mode})

            self._meta_set("num_rounds_planned", str(planned))
            self._meta_set("round_plan_json", json.dumps(plan, ensure_ascii=False))
            self._meta_set("contest_initialized", "1")
            self.conn.commit()

        except Exception as e:
            QMessageBox.critical(self, "Concours", f"Erreur sauvegarde: {e}")
            return

        QMessageBox.information(self, "Concours", "Paramètres sauvegardés.")
        self.refresh()
        self.data_changed.emit()