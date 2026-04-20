from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
)

from clubconcours.storage.repositories import RoundRepo

FORMATS = ["SINGLE", "DOUBLETTE", "TRIPLETTE"]
MODES = ["RANDOM", "AVOID_DUPLICATES", "SWISS_BY_WINS"]


class ConcoursTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)

        layout = QVBoxLayout(self)

        # --- Top settings row ---
        top = QHBoxLayout()

        top.addWidget(QLabel("Nombre de terrains:"))
        self.spin_courts = QSpinBox()
        self.spin_courts.setMinimum(1)
        self.spin_courts.setMaximum(999)
        self.spin_courts.setValue(12)
        top.addWidget(self.spin_courts)

        top.addWidget(QLabel("Nombre de parties:"))
        self.spin_rounds = QSpinBox()
        self.spin_rounds.setMinimum(1)
        self.spin_rounds.setMaximum(50)
        self.spin_rounds.setValue(4)
        top.addWidget(self.spin_rounds)

        self.btn_apply_size = QPushButton("Mettre à jour le tableau")
        self.btn_apply_size.clicked.connect(self._resize_plan_table)
        top.addWidget(self.btn_apply_size)

        top.addStretch(1)

        self.btn_save = QPushButton("Enregistrer")
        self.btn_save.clicked.connect(self._save)
        top.addWidget(self.btn_save)

        layout.addLayout(top)

        # --- Plan table ---
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Partie", "Format", "Mode tirage"])
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.refresh()

    # ---- meta helpers ----

    def _meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ---- UI ----

    def refresh(self) -> None:
        # num courts
        self.spin_courts.setValue(self.rr.get_num_courts())

        # planned rounds
        planned = self._meta_get("num_rounds_planned")
        if planned is not None:
            try:
                self.spin_rounds.setValue(int(planned))
            except Exception:
                pass

        # plan
        plan_json = self._meta_get("round_plan_json")
        plan: list[dict] = []
        if plan_json:
            try:
                plan = json.loads(plan_json)
            except Exception:
                plan = []

        # ensure table has correct number of rows
        self._resize_plan_table()

        # fill from plan
        for i in range(self.table.rowCount()):
            # defaults
            fmt = "DOUBLETTE"
            mode = "AVOID_DUPLICATES"
            if i < len(plan):
                fmt = plan[i].get("format", fmt)
                mode = plan[i].get("draw_mode", mode)

            self._set_row(i, i + 1, fmt, mode)

        self.table.resizeColumnsToContents()

    def _resize_plan_table(self) -> None:
        n = int(self.spin_rounds.value())
        self.table.setRowCount(n)

        for i in range(n):
            # Partie #
            it_num = QTableWidgetItem(str(i + 1))
            it_num.setFlags(it_num.flags() & ~it_num.flags().__class__(0x2))  # remove editable (Qt.ItemIsEditable)
            # safer explicit:
            it_num.setFlags(it_num.flags() & ~it_num.flags().ItemIsEditable)  # type: ignore[attr-defined]
            self.table.setItem(i, 0, it_num)

            # Format combo
            cb_fmt = QComboBox()
            cb_fmt.addItems(FORMATS)
            self.table.setCellWidget(i, 1, cb_fmt)

            # Mode combo
            cb_mode = QComboBox()
            cb_mode.addItems(MODES)
            self.table.setCellWidget(i, 2, cb_mode)

        self.table.resizeColumnsToContents()

    def _set_row(self, row: int, num: int, fmt: str, mode: str) -> None:
        # Partie #
        it_num = QTableWidgetItem(str(num))
        it_num.setFlags(it_num.flags() & ~it_num.flags().ItemIsEditable)  # type: ignore[attr-defined]
        self.table.setItem(row, 0, it_num)

        cb_fmt = self.table.cellWidget(row, 1)
        if isinstance(cb_fmt, QComboBox):
            cb_fmt.setCurrentText(fmt if fmt in FORMATS else "DOUBLETTE")

        cb_mode = self.table.cellWidget(row, 2)
        if isinstance(cb_mode, QComboBox):
            cb_mode.setCurrentText(mode if mode in MODES else "AVOID_DUPLICATES")

    def _save(self) -> None:
        # Save num courts via RoundRepo helper
        try:
            self.rr.set_num_courts(int(self.spin_courts.value()))
        except Exception as e:
            QMessageBox.critical(self, "Concours", str(e))
            return

        # Save planned rounds + plan json
        planned = int(self.spin_rounds.value())
        plan: list[dict] = []
        for i in range(self.table.rowCount()):
            cb_fmt = self.table.cellWidget(i, 1)
            cb_mode = self.table.cellWidget(i, 2)
            fmt = cb_fmt.currentText() if isinstance(cb_fmt, QComboBox) else "DOUBLETTE"
            mode = cb_mode.currentText() if isinstance(cb_mode, QComboBox) else "AVOID_DUPLICATES"
            plan.append({"round_number": i + 1, "format": fmt, "draw_mode": mode})

        try:
            self._meta_set("num_rounds_planned", str(planned))
            self._meta_set("round_plan_json", json.dumps(plan, ensure_ascii=False))
            self.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Concours", f"Erreur sauvegarde: {e}")
            return

        QMessageBox.information(self, "Concours", "Configuration enregistrée.")
        self.data_changed.emit()