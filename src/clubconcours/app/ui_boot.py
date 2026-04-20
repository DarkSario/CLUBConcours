from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QFileDialog,
    QMessageBox,
)

from clubconcours.storage import db
from clubconcours.storage.repositories import RoundRepo

FORMATS = ["SINGLE", "DOUBLETTE", "TRIPLETTE"]
MODES = ["RANDOM", "AVOID_DUPLICATES", "SWISS_BY_WINS"]


class BootDialog(QDialog):
    """
    Returns chosen db_path in self.db_path (Path) when accepted.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Démarrage - CLUBConcours")
        self.setModal(True)

        self.db_path: Path | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Choisis une option pour démarrer :"))

        # Buttons row
        btn_row = QHBoxLayout()
        self.btn_import = QPushButton("Importer tournoi (.db)")
        self.btn_import.clicked.connect(self._import_db)
        btn_row.addWidget(self.btn_import)

        self.btn_new = QPushButton("Nouveau tournoi")
        self.btn_new.clicked.connect(self._new_db_choose_path)
        btn_row.addWidget(self.btn_new)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("Nouveau tournoi : paramètres"))

        # Settings row
        settings = QHBoxLayout()
        settings.addWidget(QLabel("Nombre de terrains:"))
        self.spin_courts = QSpinBox()
        self.spin_courts.setMinimum(1)
        self.spin_courts.setMaximum(999)
        self.spin_courts.setValue(12)
        settings.addWidget(self.spin_courts)

        settings.addWidget(QLabel("Nombre de parties:"))
        self.spin_rounds = QSpinBox()
        self.spin_rounds.setMinimum(1)
        self.spin_rounds.setMaximum(50)
        self.spin_rounds.setValue(4)
        self.spin_rounds.valueChanged.connect(self._resize_plan_table)
        settings.addWidget(self.spin_rounds)

        layout.addLayout(settings)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Partie", "Format", "Mode tirage"])
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Bottom
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_cancel = QPushButton("Quitter")
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)
        layout.addLayout(bottom)

        self._resize_plan_table()

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
                cb_mode.addItems(MODES)
                cb_mode.setCurrentText("AVOID_DUPLICATES")
                self.table.setCellWidget(i, 2, cb_mode)

        self.table.resizeColumnsToContents()

    def _build_plan(self) -> list[dict]:
        plan: list[dict] = []
        for i in range(self.table.rowCount()):
            cb_fmt = self.table.cellWidget(i, 1)
            cb_mode = self.table.cellWidget(i, 2)
            fmt = cb_fmt.currentText() if isinstance(cb_fmt, QComboBox) else "DOUBLETTE"
            mode = cb_mode.currentText() if isinstance(cb_mode, QComboBox) else "AVOID_DUPLICATES"
            plan.append({"round_number": i + 1, "format": fmt, "draw_mode": mode})
        return plan

    def _import_db(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Importer un tournoi", "", "SQLite DB (*.db)")
        if not filename:
            return
        p = Path(filename)
        if not p.exists():
            QMessageBox.critical(self, "Importer", "Fichier introuvable.")
            return

        # quick sanity check (openable)
        try:
            conn = db.connect(str(p))
            db.init_db(conn)
            conn.close()
        except Exception as e:
            QMessageBox.critical(self, "Importer", f"DB invalide: {e}")
            return

        self.db_path = p
        self.accept()

    def _new_db_choose_path(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Créer un nouveau tournoi",
            "CLUBConcours.db",
            "SQLite DB (*.db)",
        )
        if not filename:
            return

        p = Path(filename)
        if p.suffix.lower() != ".db":
            p = p.with_suffix(".db")

        # create / init db
        try:
            conn = db.connect(str(p))
            db.init_db(conn)

            rr = RoundRepo(conn)
            rr.set_num_courts(int(self.spin_courts.value()))

            planned = int(self.spin_rounds.value())
            plan = self._build_plan()

            conn.execute(
                "INSERT INTO meta(key, value) VALUES('num_rounds_planned', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(planned),),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('round_plan_json', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(plan, ensure_ascii=False),),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('contest_initialized', '1') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
            )
            conn.commit()
            conn.close()

        except Exception as e:
            QMessageBox.critical(self, "Nouveau tournoi", f"Erreur création DB: {e}")
            return

        self.db_path = p
        self.accept()