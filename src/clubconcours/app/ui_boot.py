from __future__ import annotations

import json
from datetime import date
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
    QLineEdit,
    QFormLayout,
    QDateEdit,
    QHeaderView,
)

from clubconcours.storage import db
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

        layout.addWidget(QLabel("Nouveau tournoi : informations"))

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Ex: Concours du vendredi")
        form.addRow("Nom du concours:", self.name_edit)

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(date.today())
        form.addRow("Date:", self.date_edit)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Ex: Boulodrome municipal – Club XYZ")
        form.addRow("Lieu / Club:", self.location_edit)

        layout.addLayout(form)

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
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # Help under table
        self.mode_help = QLabel("")
        self.mode_help.setStyleSheet("color: #666;")
        layout.addWidget(self.mode_help)

        # Bottom
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_cancel = QPushButton("Quitter")
        self.btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(self.btn_cancel)
        layout.addLayout(bottom)

        self._resize_plan_table()
        self._update_mode_help()

    def _setup_table_columns(self) -> None:
        """
        Prevent truncated text: keep col 0 fixed and let col 1/2 stretch.
        Avoid resizeColumnsToContents() because embedded comboboxes + QSS make it jitter.
        """
        h = self.table.horizontalHeader()

        self.table.setColumnWidth(0, 70)
        h.setSectionResizeMode(0, QHeaderView.Fixed)

        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 260)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Stretch)

        h.setStretchLastSection(True)

    def _populate_mode_combo(self, combo: QComboBox) -> None:
        combo.clear()
        for code in MODES:
            combo.addItem(DRAW_MODE_LABELS.get(code, code), code)
            combo.setItemData(combo.count() - 1, DRAW_MODE_HELP.get(code, ""), role=Qt.ToolTipRole)

        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(18)

    def _setup_format_combo(self, combo: QComboBox) -> None:
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)

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
                self._setup_format_combo(cb_fmt)
                self.table.setCellWidget(i, 1, cb_fmt)

            cb_mode = self.table.cellWidget(i, 2)
            if not isinstance(cb_mode, QComboBox):
                cb_mode = QComboBox()
                self._populate_mode_combo(cb_mode)
                self._set_mode_combo_by_code(cb_mode, "AVOID_DUPLICATES")
                cb_mode.currentIndexChanged.connect(self._update_mode_help)
                self.table.setCellWidget(i, 2, cb_mode)

        self.table.currentCellChanged.connect(lambda *_: self._update_mode_help())
        self._setup_table_columns()
        self._update_mode_help()

    def _build_plan(self) -> list[dict]:
        plan: list[dict] = []
        for i in range(self.table.rowCount()):
            cb_fmt = self.table.cellWidget(i, 1)
            cb_mode = self.table.cellWidget(i, 2)
            fmt = cb_fmt.currentText() if isinstance(cb_fmt, QComboBox) else "DOUBLETTE"
            mode = self._mode_code_from_combo(cb_mode) if isinstance(cb_mode, QComboBox) else "AVOID_DUPLICATES"
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

        tournament_name = self.name_edit.text().strip()
        tournament_date = self.date_edit.date().toPython().isoformat()
        tournament_location = self.location_edit.text().strip()

        if not tournament_name:
            QMessageBox.warning(self, "Nouveau tournoi", "Le nom du concours est obligatoire.")
            return

        try:
            conn = db.connect(str(p))
            db.init_db(conn)

            rr = RoundRepo(conn)
            rr.set_num_courts(int(self.spin_courts.value()))

            planned = int(self.spin_rounds.value())
            plan = self._build_plan()

            # Tournament info
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('tournament_name', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (tournament_name,),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('tournament_date', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (tournament_date,),
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('tournament_location', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (tournament_location,),
            )

            # Contest plan
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