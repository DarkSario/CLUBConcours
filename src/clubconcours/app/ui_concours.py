from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Signal, Qt
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
    QFileDialog,
)

from clubconcours.storage import db
from clubconcours.storage.repositories import RoundRepo

FORMATS = ["SINGLE", "DOUBLETTE", "TRIPLETTE"]
MODES = ["RANDOM", "AVOID_DUPLICATES", "SWISS_BY_WINS"]


class ConcoursTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection, on_db_switch: Callable[[Path], None]) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)
        self.on_db_switch = on_db_switch

        layout = QVBoxLayout(self)

        # --- Buttons row (init / save / import) ---
        btn_row = QHBoxLayout()

        self.btn_init = QPushButton("Initialiser concours (nouvelle DB)")
        self.btn_init.clicked.connect(self._init_contest_new_db)
        btn_row.addWidget(self.btn_init)

        self.btn_save_db = QPushButton("Sauvegarder…")
        self.btn_save_db.clicked.connect(self._save_db_copy)
        btn_row.addWidget(self.btn_save_db)

        self.btn_import_db = QPushButton("Importer…")
        self.btn_import_db.clicked.connect(self._import_db)
        btn_row.addWidget(self.btn_import_db)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # --- Settings row ---
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

        self.btn_save = QPushButton("Enregistrer config")
        self.btn_save.clicked.connect(self._save_config_only)
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

    def _build_plan_from_table(self) -> list[dict]:
        plan: list[dict] = []
        for i in range(self.table.rowCount()):
            cb_fmt = self.table.cellWidget(i, 1)
            cb_mode = self.table.cellWidget(i, 2)
            fmt = cb_fmt.currentText() if isinstance(cb_fmt, QComboBox) else "DOUBLETTE"
            mode = cb_mode.currentText() if isinstance(cb_mode, QComboBox) else "AVOID_DUPLICATES"
            plan.append({"round_number": i + 1, "format": fmt, "draw_mode": mode})
        return plan

    # ---- UI ----

    def refresh(self) -> None:
        self.spin_courts.setValue(self.rr.get_num_courts())

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
            self._set_row(i, i + 1, fmt, mode)

        self.table.resizeColumnsToContents()

    def _resize_plan_table(self) -> None:
        n = int(self.spin_rounds.value())
        self.table.setRowCount(n)

        for i in range(n):
            it_num = QTableWidgetItem(str(i + 1))
            it_num.setFlags(it_num.flags() & ~Qt.ItemIsEditable)
            it_num.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 0, it_num)

            cb_fmt = QComboBox()
            cb_fmt.addItems(FORMATS)
            self.table.setCellWidget(i, 1, cb_fmt)

            cb_mode = QComboBox()
            cb_mode.addItems(MODES)
            self.table.setCellWidget(i, 2, cb_mode)

    def _set_row(self, row: int, num: int, fmt: str, mode: str) -> None:
        it_num = QTableWidgetItem(str(num))
        it_num.setFlags(it_num.flags() & ~Qt.ItemIsEditable)
        it_num.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, it_num)

        cb_fmt = self.table.cellWidget(row, 1)
        if isinstance(cb_fmt, QComboBox):
            cb_fmt.setCurrentText(fmt if fmt in FORMATS else "DOUBLETTE")

        cb_mode = self.table.cellWidget(row, 2)
        if isinstance(cb_mode, QComboBox):
            cb_mode.setCurrentText(mode if mode in MODES else "AVOID_DUPLICATES")

    # ---- actions ----

    def _save_config_only(self) -> None:
        try:
            self.rr.set_num_courts(int(self.spin_courts.value()))

            planned = int(self.spin_rounds.value())
            plan = self._build_plan_from_table()

            self._meta_set("num_rounds_planned", str(planned))
            self._meta_set("round_plan_json", json.dumps(plan, ensure_ascii=False))
            self.conn.commit()

        except Exception as e:
            QMessageBox.critical(self, "Concours", f"Erreur sauvegarde: {e}")
            return

        QMessageBox.information(self, "Concours", "Configuration enregistrée.")
        self.data_changed.emit()

    def _init_contest_new_db(self) -> None:
        # confirm
        ok = QMessageBox.question(
            self,
            "Initialiser concours",
            "Créer un nouveau fichier DB et initialiser le concours ?\n"
            "Cela ne supprime pas l'ancienne DB.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return

        # create new DB and apply config
        new_path = Path(db.default_db_filename("CLUBConcours"))
        conn2 = db.connect(str(new_path))
        db.init_db(conn2)
        rr2 = RoundRepo(conn2)

        try:
            rr2.set_num_courts(int(self.spin_courts.value()))
            planned = int(self.spin_rounds.value())
            plan = self._build_plan_from_table()

            conn2.execute(
                "INSERT INTO meta(key, value) VALUES('num_rounds_planned', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(planned),),
            )
            conn2.execute(
                "INSERT INTO meta(key, value) VALUES('round_plan_json', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(plan, ensure_ascii=False),),
            )
            conn2.execute(
                "INSERT INTO meta(key, value) VALUES('contest_initialized', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            conn2.commit()
        finally:
            conn2.close()

        self.on_db_switch(new_path)

    def _save_db_copy(self) -> None:
        # current db file path is not directly stored here; we ask user where to save, and copy
        # We'll infer current DB path from PRAGMA database_list (main file).
        row = self.conn.execute("PRAGMA database_list").fetchone()
        if row is None or not row["file"]:
            QMessageBox.critical(self, "Sauvegarder", "Impossible de déterminer le fichier DB courant.")
            return
        src = Path(str(row["file"]))

        dst_name, _ = QFileDialog.getSaveFileName(
            self,
            "Sauvegarder la base",
            str(src.with_name(src.stem + "_backup.db")),
            "SQLite DB (*.db)",
        )
        if not dst_name:
            return

        try:
            shutil.copy2(src, Path(dst_name))
        except Exception as e:
            QMessageBox.critical(self, "Sauvegarder", f"Erreur copie: {e}")
            return

        QMessageBox.information(self, "Sauvegarder", "Sauvegarde effectuée.")

    def _import_db(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Importer une base",
            "",
            "SQLite DB (*.db)",
        )
        if not filename:
            return

        p = Path(filename)
        if not p.exists():
            QMessageBox.critical(self, "Importer", "Fichier introuvable.")
            return

        self.on_db_switch(p)