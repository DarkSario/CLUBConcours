from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QMessageBox,
)

from clubconcours.storage import db
from clubconcours.app.ui_players import PlayersTab
from clubconcours.app.ui_draw import DrawTab
from clubconcours.app.ui_scores import ScoresTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CLUBConcours")

        # DB
        self.db_path = Path(db.default_db_filename("CLUBConcours"))
        self.conn = db.connect(str(self.db_path))
        db.init_db(self.conn)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.players_tab = PlayersTab(self.conn)
        self.draw_tab = DrawTab(self.conn)
        self.scores_tab = ScoresTab(self.conn)

        self.tabs.addTab(self.players_tab, "Joueurs")
        self.tabs.addTab(self.draw_tab, "Tirage")
        self.tabs.addTab(self.scores_tab, "Scores")

        # Wiring: refresh other tabs when something changes
        self.players_tab.data_changed.connect(self._refresh_all)
        self.draw_tab.data_changed.connect(self._refresh_all)
        self.scores_tab.data_changed.connect(self._refresh_all)

        self._refresh_all()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.conn.close()
        except Exception as e:
            QMessageBox.warning(self, "DB", f"Erreur fermeture DB: {e}")
        event.accept()

    def _refresh_all(self) -> None:
        self.players_tab.refresh()
        self.draw_tab.refresh()
        self.scores_tab.refresh()