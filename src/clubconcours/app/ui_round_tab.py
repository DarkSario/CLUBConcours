from __future__ import annotations

import html
import sqlite3

from PySide6.QtCore import Signal, Qt, QRectF
from PySide6.QtGui import QColor, QKeySequence, QTextDocument, QBrush
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QApplication,
    QStyledItemDelegate,
    QStyle,
    QHeaderView,
    QFrame,
)

from clubconcours.storage.repositories import RoundRepo


def wins_to_color(wins: int) -> QColor:
    if wins <= 0:
        return QColor("#6B7280")
    if wins == 1:
        return QColor("#2563EB")
    if wins == 2:
        return QColor("#16A34A")
    if wins == 3:
        return QColor("#D97706")
    return QColor("#DC2626")


class HtmlDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):  # type: ignore[override]
        text = index.data(Qt.DisplayRole)
        if isinstance(text, str) and ("</" in text or "<span" in text or "<b>" in text):
            doc = QTextDocument()
            doc.setDefaultFont(option.font)
            doc.setHtml(text)

            painter.save()
            try:
                if option.state & QStyle.State_Selected:
                    painter.fillRect(option.rect, option.palette.highlight())

                painter.translate(option.rect.left() + 4, option.rect.top() + 2)
                clip = QRectF(0, 0, option.rect.width() - 8, option.rect.height() - 4)
                doc.setTextWidth(clip.width())
                doc.drawContents(painter, clip)
            finally:
                painter.restore()
        else:
            super().paint(painter, option, index)


class ScoresPasteTableWidget(QTableWidget):
    def __init__(self, parent: "RoundTab") -> None:
        super().__init__(0, 7, parent)
        self._round_tab = parent

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.matches(QKeySequence.Paste):
            self._round_tab.paste_scores_from_clipboard()
            return
        super().keyPressEvent(event)


class RoundTab(QWidget):
    data_changed = Signal()

    COL_MATCH_ID = 0
    COL_TERRAIN = 1
    COL_TEAM1 = 2
    COL_SCORE1 = 3
    COL_SCORE2 = 4
    COL_TEAM2 = 5
    COL_STATUS = 6

    def __init__(self, conn: sqlite3.Connection, round_id: int) -> None:
        super().__init__()
        self.conn = conn
        self.rr = RoundRepo(conn)
        self.round_id = round_id

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

        header = QHBoxLayout()
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("font-weight:700; font-size: 12pt;")
        header.addWidget(self.lbl_title)
        header.addStretch(1)

        self.btn_assign = QPushButton("Retirer terrains")
        self.btn_assign.clicked.connect(self.assign_courts)
        header.addWidget(self.btn_assign)

        self.btn_save = QPushButton("Enregistrer scores")
        self.btn_save.setProperty("primary", True)
        self.btn_save.clicked.connect(self.save_scores)
        header.addWidget(self.btn_save)

        self.btn_validate = QPushButton("Valider la partie")
        self.btn_validate.setProperty("primary", True)
        self.btn_validate.clicked.connect(self.validate_round)
        header.addWidget(self.btn_validate)

        self.btn_unlock = QPushButton("Déverrouiller")
        self.btn_unlock.setProperty("danger", True)
        self.btn_unlock.clicked.connect(self.unlock_round)
        header.addWidget(self.btn_unlock)

        layout.addLayout(header)

        self.table = ScoresPasteTableWidget(self)
        self.table.setHorizontalHeaderLabels(
            ["Match ID", "Terrain", "Equipe A", "Score A", "Score B", "Equipe B", "Statut"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)

        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setSelectionBehavior(QTableWidget.SelectItems)

        self._html_delegate = HtmlDelegate(self.table)
        self.table.setItemDelegateForColumn(self.COL_TEAM1, self._html_delegate)
        self.table.setItemDelegateForColumn(self.COL_TEAM2, self._html_delegate)

        self._setup_column_sizing()
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.verticalHeader().setVisible(False)

        layout.addWidget(self.table)

        self.refresh()

    def _setup_column_sizing(self) -> None:
        h = self.table.horizontalHeader()

        self.table.setColumnWidth(self.COL_MATCH_ID, 70)
        self.table.setColumnWidth(self.COL_TERRAIN, 70)
        self.table.setColumnWidth(self.COL_SCORE1, 70)
        self.table.setColumnWidth(self.COL_SCORE2, 70)
        self.table.setColumnWidth(self.COL_STATUS, 120)

        h.setSectionResizeMode(self.COL_TEAM1, QHeaderView.Stretch)
        h.setSectionResizeMode(self.COL_TEAM2, QHeaderView.Stretch)

        h.setSectionResizeMode(self.COL_MATCH_ID, QHeaderView.Fixed)
        h.setSectionResizeMode(self.COL_TERRAIN, QHeaderView.Fixed)
        h.setSectionResizeMode(self.COL_SCORE1, QHeaderView.Fixed)
        h.setSectionResizeMode(self.COL_SCORE2, QHeaderView.Fixed)
        h.setSectionResizeMode(self.COL_STATUS, QHeaderView.Fixed)
        h.setStretchLastSection(False)

        self.table.setWordWrap(False)

    def _is_locked(self) -> bool:
        r = self.conn.execute(
            "SELECT scores_locked, validated FROM rounds WHERE id=?",
            (self.round_id,),
        ).fetchone()
        if r is None:
            return False
        return int(r["scores_locked"]) == 1 or int(r["validated"]) == 1

    def _wins_by_player_name(self) -> dict[str, int]:
        players = self.conn.execute("SELECT id, name FROM players").fetchall()
        id_to_name = {int(p["id"]): str(p["name"]) for p in players}

        team_players = self.conn.execute("SELECT round_team_id, player_id FROM round_team_players").fetchall()
        team_to_players: dict[int, list[int]] = {}
        for r in team_players:
            team_to_players.setdefault(int(r["round_team_id"]), []).append(int(r["player_id"]))

        wins_by_name: dict[str, int] = {name: 0 for name in id_to_name.values()}

        matches = self.conn.execute(
            "SELECT team1_id, team2_id, score1, score2 FROM matches WHERE validated=1"
        ).fetchall()

        for m in matches:
            t1 = int(m["team1_id"])
            t2 = m["team2_id"]
            s1 = m["score1"]
            s2 = m["score2"]
            if s1 is None or s2 is None:
                continue

            p1 = team_to_players.get(t1, [])
            p2 = team_to_players.get(int(t2), []) if t2 is not None else []

            if int(s1) > int(s2):
                for pid in p1:
                    n = id_to_name.get(pid)
                    if n is not None:
                        wins_by_name[n] = wins_by_name.get(n, 0) + 1
            elif int(s2) > int(s1):
                for pid in p2:
                    n = id_to_name.get(pid)
                    if n is not None:
                        wins_by_name[n] = wins_by_name.get(n, 0) + 1

        return wins_by_name

    def _team_names(self, team_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT p.name
            FROM round_team_players rtp
            JOIN players p ON p.id = rtp.player_id
            WHERE rtp.round_team_id=?
            ORDER BY p.name COLLATE NOCASE
            """,
            (team_id,),
        ).fetchall()
        return [str(r["name"]) for r in rows]

    def _team_label_html(self, team_id: int, wins_by_name: dict[str, int]) -> str:
        names = self._team_names(team_id)
        parts: list[str] = []
        for n in names:
            w = int(wins_by_name.get(n, 0))
            c = wins_to_color(w).name()
            parts.append(f'<span style="color:{c}; font-weight:700;">{html.escape(n)}</span>')
        return " / ".join(parts)

    def _refresh_dashboard(self, round_number: int, locked: bool) -> None:
        n_matches = int(
            self.conn.execute("SELECT COUNT(*) AS n FROM matches WHERE round_id=?", (self.round_id,)).fetchone()["n"]
        )
        n_valid = int(
            self.conn.execute(
                "SELECT COUNT(*) AS n FROM matches WHERE round_id=? AND validated=1",
                (self.round_id,),
            ).fetchone()["n"]
        )
        missing = int(
            self.conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM matches
                WHERE round_id=?
                  AND team2_id IS NOT NULL
                  AND (score1 IS NULL OR score2 IS NULL)
                """,
                (self.round_id,),
            ).fetchone()["n"]
        )
        self.lbl_dash.setText(
            f"Partie {round_number}  |  Matchs: {n_matches}  |  Validés: {n_valid}  |  Scores manquants: {missing}  |  "
            f"{'VERROUILLÉ' if locked else 'OUVERT'}"
        )

    def refresh(self) -> None:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (self.round_id,)).fetchone()
        if r is None:
            self.lbl_title.setText(f"Partie introuvable (id={self.round_id})")
            return

        locked = self._is_locked()
        round_number = int(r["number"])
        self.lbl_title.setText(f"Partie {round_number}  |  {r['format']}  |  {r['draw_mode']}")

        self._refresh_dashboard(round_number, locked)

        wins_by_name = self._wins_by_player_name()

        matches = self.conn.execute(
            """
            SELECT m.id, m.team1_id, m.team2_id, m.score1, m.score2, m.validated,
                   ca.court_number AS court_number
            FROM matches m
            LEFT JOIN court_assignments ca ON ca.match_id = m.id
            WHERE m.round_id=?
            ORDER BY m.id
            """,
            (self.round_id,),
        ).fetchall()

        self.table.setRowCount(0)

        col_ok = QColor("#22C55E")
        col_muted = QColor("#9CA3AF")
        col_exempt = QColor("#6B7280")
        bg_missing = QBrush(QColor("#3B2A0A"))  # dark amber
        bg_none = QBrush(Qt.transparent)

        for m in matches:
            row = self.table.rowCount()
            self.table.insertRow(row)

            match_id = int(m["id"])
            team1_id = int(m["team1_id"])
            team2_id = m["team2_id"]  # can be None
            is_exempt = team2_id is None

            it_id = QTableWidgetItem(str(match_id))
            it_id.setFlags(it_id.flags() & ~Qt.ItemIsEditable)
            it_id.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_MATCH_ID, it_id)

            court = m["court_number"]
            it_court = QTableWidgetItem("" if court is None else str(int(court)))
            it_court.setTextAlignment(Qt.AlignCenter)
            it_court.setFlags(it_court.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TERRAIN, it_court)

            it_t1 = QTableWidgetItem(self._team_label_html(team1_id, wins_by_name))
            it_t1.setFlags(it_t1.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TEAM1, it_t1)

            if is_exempt:
                t2_html = '<span style="font-weight:700; color:#9CA3AF;">EXEMPT</span>'
            else:
                t2_html = self._team_label_html(int(team2_id), wins_by_name)
            it_t2 = QTableWidgetItem(t2_html)
            it_t2.setFlags(it_t2.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, self.COL_TEAM2, it_t2)

            s1 = m["score1"]
            s2 = m["score2"]
            it_s1 = QTableWidgetItem("" if s1 is None else str(int(s1)))
            it_s2 = QTableWidgetItem("" if s2 is None else str(int(s2)))
            it_s1.setTextAlignment(Qt.AlignCenter)
            it_s2.setTextAlignment(Qt.AlignCenter)

            if locked or is_exempt:
                it_s1.setFlags(it_s1.flags() & ~Qt.ItemIsEditable)
                it_s2.setFlags(it_s2.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(row, self.COL_SCORE1, it_s1)
            self.table.setItem(row, self.COL_SCORE2, it_s2)

            validated = int(m["validated"]) == 1

            if is_exempt:
                it_status = QTableWidgetItem("EXEMPT")
                it_status.setForeground(col_exempt)
            else:
                it_status = QTableWidgetItem("VALIDÉ" if validated else "NON VALIDÉ")
                it_status.setForeground(col_ok if validated else col_muted)

            it_status.setFlags(it_status.flags() & ~Qt.ItemIsEditable)
            it_status.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, self.COL_STATUS, it_status)

            missing = (not is_exempt) and ((s1 is None) or (s2 is None))
            it_s1.setBackground(bg_missing if (missing and s1 is None) else bg_none)
            it_s2.setBackground(bg_missing if (missing and s2 is None) else bg_none)

            if is_exempt:
                for c in range(self.table.columnCount()):
                    it = self.table.item(row, c)
                    if it is not None and c not in (self.COL_TEAM1, self.COL_TEAM2):
                        it.setForeground(col_exempt)

        self._setup_column_sizing()

        self.btn_save.setEnabled(not locked)
        self.btn_validate.setEnabled(not locked)
        self.btn_assign.setEnabled(not locked)
        self.btn_unlock.setEnabled(locked)

    def paste_scores_from_clipboard(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Coller scores", "Partie verrouillée.")
            return

        idx = self.table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "Coller scores", "Clique d'abord dans une cellule (Score A ou Score B).")
            return

        start_row = idx.row()
        start_col = idx.column()
        if start_col not in (self.COL_SCORE1, self.COL_SCORE2):
            start_col = self.COL_SCORE1

        text = (QApplication.clipboard().text() or "").strip("\n\r")
        if not text.strip():
            return

        team2_by_match = {
            int(r["id"]): r["team2_id"]
            for r in self.conn.execute(
                "SELECT id, team2_id FROM matches WHERE round_id=?",
                (self.round_id,),
            ).fetchall()
        }

        in_rows = [r for r in text.splitlines() if r.strip() != ""]
        matrix: list[list[str]] = [[c.strip() for c in r.split("\t")] for r in in_rows]

        errors: list[str] = []
        applied = 0

        src_r = 0
        dst_row = start_row
        while src_r < len(matrix) and dst_row < self.table.rowCount():
            mid_item = self.table.item(dst_row, self.COL_MATCH_ID)
            if mid_item is None:
                dst_row += 1
                continue

            match_id = int(mid_item.text())
            if team2_by_match.get(match_id) is None:
                dst_row += 1
                continue

            src_cols = matrix[src_r]
            for src_c, raw in enumerate(src_cols):
                dst_col = start_col + src_c
                if dst_col not in (self.COL_SCORE1, self.COL_SCORE2):
                    break
                if raw == "":
                    continue

                try:
                    n = int(raw)
                except Exception:
                    errors.append(f"Ligne {src_r+1}: '{raw}' n'est pas un entier")
                    continue

                if n < 0 or n > 13:
                    errors.append(f"Ligne {src_r+1}: score {n} hors plage (0..13)")
                    continue

                it = self.table.item(dst_row, dst_col)
                if it is None:
                    it = QTableWidgetItem("")
                    it.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(dst_row, dst_col, it)
                it.setText(str(n))
                applied += 1

            src_r += 1
            dst_row += 1

        if errors:
            QMessageBox.warning(
                self,
                "Coller scores",
                "Certaines valeurs n'ont pas été collées :\n\n" + "\n".join(errors[:15]),
            )

        if applied > 0:
            self.table.setFocus()

    def save_scores(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Scores", "Partie verrouillée.")
            return

        team2_by_match = {
            int(r["id"]): r["team2_id"]
            for r in self.conn.execute(
                "SELECT id, team2_id FROM matches WHERE round_id=?",
                (self.round_id,),
            ).fetchall()
        }

        try:
            for row in range(self.table.rowCount()):
                match_id = int(self.table.item(row, self.COL_MATCH_ID).text())
                if team2_by_match.get(match_id) is None:
                    continue

                s1_txt = (self.table.item(row, self.COL_SCORE1).text() or "").strip()
                s2_txt = (self.table.item(row, self.COL_SCORE2).text() or "").strip()

                s1 = int(s1_txt) if s1_txt != "" else None
                s2 = int(s2_txt) if s2_txt != "" else None

                self.rr.set_match_score(match_id, s1, s2)

        except Exception as e:
            QMessageBox.critical(self, "Scores", f"Erreur enregistrement scores: {e}")
            return

        self.refresh()
        self.data_changed.emit()

    def assign_courts(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Terrains", "Partie verrouillée.")
            return
        try:
            self.rr.assign_courts_for_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Terrains", str(e))
            return
        self.refresh()
        self.data_changed.emit()

    def validate_round(self) -> None:
        if self._is_locked():
            QMessageBox.information(self, "Validation", "Partie déjà verrouillée.")
            return

        self.save_scores()
        try:
            self.rr.validate_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Validation", str(e))
            return

        QMessageBox.information(self, "Validation", "Partie validée (scores + terrains verrouillés).")
        self.refresh()
        self.data_changed.emit()

    def unlock_round(self) -> None:
        if not self._is_locked():
            return

        ok = QMessageBox.question(
            self,
            "Déverrouiller",
            "Déverrouiller cette partie ?\n"
            "Cela permettra de modifier les scores et les terrains.\n\n"
            "Confirmer ?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return

        try:
            self.rr.unlock_round(self.round_id)
        except Exception as e:
            QMessageBox.critical(self, "Déverrouiller", str(e))
            return

        self.refresh()
        self.data_changed.emit()