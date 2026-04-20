from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QMessageBox,
)

from clubconcours.storage import db
from clubconcours.app.ui_concours import ConcoursTab
from clubconcours.app.ui_players import PlayersTab
from clubconcours.app.ui_draw import DrawTab
from clubconcours.app.ui_round_tab import RoundTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CLUBConcours")

        # DB
        self.db_path = Path(db.default_db_filename("CLUBConcours"))
        self.conn = db.connect(str(self.db_path))
        db.init_db(self.conn)

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.setCentralWidget(self.tabs)

        self.concours_tab = ConcoursTab(self.conn)
        self.players_tab = PlayersTab(self.conn)
        self.draw_tab = DrawTab(self.conn)

        self.tabs.addTab(self.concours_tab, "Concours")
        self.tabs.addTab(self.players_tab, "Joueurs")
        self.tabs.addTab(self.draw_tab, "Tirage")

        # Map round_id -> tab
        self.round_tabs: dict[int, RoundTab] = {}

        # Wiring
        self.concours_tab.data_changed.connect(self._refresh_all)
        self.players_tab.data_changed.connect(self._refresh_all)
        self.draw_tab.data_changed.connect(self._refresh_all)
        self.draw_tab.round_created.connect(self._open_round_tab)

        self._refresh_all()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.conn.close()
        except Exception as e:
            QMessageBox.warning(self, "DB", f"Erreur fermeture DB: {e}")
        event.accept()

    def _refresh_all(self) -> None:
        self.concours_tab.refresh()
        self.players_tab.refresh()
        self.draw_tab.refresh()
        self._sync_round_tabs()

    def _sync_round_tabs(self) -> None:
        rounds = self.conn.execute(
            "SELECT id, number FROM rounds ORDER BY number"
        ).fetchall()

        for r in rounds:
            rid = int(r["id"])
            if rid not in self.round_tabs:
                tab = RoundTab(self.conn, rid)
                tab.data_changed.connect(self._refresh_all)
                self.round_tabs[rid] = tab
                self.tabs.addTab(tab, f"Partie {r['number']}")

        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, RoundTab):
                rr = self.conn.execute("SELECT number FROM rounds WHERE id=?", (w.round_id,)).fetchone()
                if rr is not None:
                    self.tabs.setTabText(i, f"Partie {int(rr['number'])}")

    def _open_round_tab(self, round_id: int) -> None:
        self._sync_round_tabs()

        tab = self.round_tabs.get(round_id)
        if tab is None:
            return
        for i in range(self.tabs.count()):
            if self.tabs.widget(i) is tab:
                self.tabs.setCurrentIndex(i)
                tab.refresh()
                break