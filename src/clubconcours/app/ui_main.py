from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QTabWidget, QMessageBox, QStatusBar, QLabel

from clubconcours.storage import db
from clubconcours.app.ui_players import PlayersTab
from clubconcours.app.ui_concours import ConcoursTab
from clubconcours.app.ui_draw import DrawTab
from clubconcours.app.ui_round_tab import RoundTab
from clubconcours.app.ui_ranking import RankingTab
from clubconcours.app.ui_export import ExportTab


def _icon(name: str) -> QIcon:
    # assets/icons/<name>.svg (relative to this file)
    p = Path(__file__).resolve().parent / "assets" / "icons" / f"{name}.svg"
    if p.exists():
        return QIcon(str(p))
    return QIcon()


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("CLUBConcours")

        self.db_path = db_path
        self.conn = db.connect(str(self.db_path))
        db.init_db(self.conn)

        self.tabs = QTabWidget()
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.setCentralWidget(self.tabs)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._sb_left = QLabel("")
        self._sb_mid = QLabel("")
        self._sb_right = QLabel("")
        self._sb_left.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._sb_mid.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._sb_right.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sb.addWidget(self._sb_left, 2)
        sb.addWidget(self._sb_mid, 1)
        sb.addPermanentWidget(self._sb_right, 1)

        # Tabs
        self.players_tab = PlayersTab(self.conn)
        self.concours_tab = ConcoursTab(self.conn)
        self.draw_tab = DrawTab(self.conn)
        self.ranking_tab = RankingTab(self.conn)
        self.export_tab = ExportTab(self.conn)

        self.tabs.addTab(self.players_tab, _icon("users"), "Inscription")
        self.tabs.addTab(self.concours_tab, _icon("settings"), "Concours")
        self.tabs.addTab(self.draw_tab, _icon("dice"), "Tirage")
        self.tabs.addTab(self.ranking_tab, _icon("trophy"), "Classement")
        self.tabs.addTab(self.export_tab, _icon("export"), "Export")

        self.round_tabs: dict[int, RoundTab] = {}

        # Wiring
        self.players_tab.data_changed.connect(self._refresh_all)
        self.concours_tab.data_changed.connect(self._refresh_all)
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
        self.players_tab.refresh()
        self.concours_tab.refresh()
        self.draw_tab.refresh()
        self.ranking_tab.refresh()
        self._sync_round_tabs()
        self._refresh_status_bar()

    def _refresh_status_bar(self) -> None:
        players = self.conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()
        n_players = int(players["n"]) if players else 0

        validated = self.conn.execute("SELECT COUNT(*) AS n FROM matches WHERE validated=1").fetchone()
        n_validated = int(validated["n"]) if validated else 0

        current_round = self.conn.execute("SELECT COALESCE(MAX(number), 0) AS m FROM rounds").fetchone()
        cur = int(current_round["m"]) if current_round else 0

        planned_row = self.conn.execute("SELECT value FROM meta WHERE key='num_rounds_planned'").fetchone()
        planned = int(planned_row["value"]) if planned_row and str(planned_row["value"]).isdigit() else None

        init_row = self.conn.execute("SELECT value FROM meta WHERE key='contest_initialized'").fetchone()
        initialized = init_row is not None and str(init_row["value"]) == "1"

        self._sb_left.setText(f"DB: {self.db_path}")
        self._sb_mid.setText(f"Joueurs: {n_players}  |  Matchs validés: {n_validated}")
        if planned is None:
            self._sb_right.setText(f"Concours: {'OK' if initialized else 'NON'}  |  Partie: {cur}")
        else:
            self._sb_right.setText(f"Concours: {'OK' if initialized else 'NON'}  |  Partie: {cur}/{planned}")

    def _sync_round_tabs(self) -> None:
        rounds = self.conn.execute("SELECT id, number FROM rounds ORDER BY number").fetchall()

        for r in rounds:
            rid = int(r["id"])
            if rid not in self.round_tabs:
                tab = RoundTab(self.conn, rid)
                tab.data_changed.connect(self._refresh_all)
                self.round_tabs[rid] = tab
                self.tabs.addTab(tab, _icon("round"), f"Partie {r['number']}")

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