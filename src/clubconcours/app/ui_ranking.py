from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from clubconcours.core.ranking import compute_player_ranking


class RankingTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        self.title = QLabel("Classement Général")
        self.title.setStyleSheet("font-weight: 700; font-size: 18px;")
        top.addWidget(self.title)

        top.addStretch(1)

        self.btn_export = QPushButton("Exporter PDF…")
        self.btn_export.clicked.connect(self._export_pdf)
        top.addWidget(self.btn_export)

        layout.addLayout(top)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Rang", "Joueur", "Victoires", "Points gagnés", "Points perdus", "Goal Average"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        layout.addWidget(self.table)

        self.refresh()

    def _meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def refresh(self) -> None:
        ranking = compute_player_ranking(self.conn)

        self.table.setRowCount(len(ranking))
        for i, s in enumerate(ranking, start=1):
            items = [
                QTableWidgetItem(str(i)),
                QTableWidgetItem(str(s.name)),
                QTableWidgetItem(str(s.wins)),
                QTableWidgetItem(str(s.plus)),
                QTableWidgetItem(str(s.minus)),
                QTableWidgetItem(str(s.ga)),
            ]
            for j, it in enumerate(items):
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if j != 1:
                    it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i - 1, j, it)

        self.table.resizeColumnsToContents()

    def _export_pdf(self) -> None:
        tournament_name = self._meta_get("tournament_name") or "CLUBConcours"
        tournament_date = self._meta_get("tournament_date") or ""
        tournament_location = self._meta_get("tournament_location") or ""

        ranking = compute_player_ranking(self.conn)

        default_name = f"{tournament_name}_classement.pdf".replace("/", "-").replace("\\", "-")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter le classement en PDF",
            default_name,
            "PDF (*.pdf)",
        )
        if not filename:
            return

        out = Path(filename)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")

        try:
            self._build_pdf(
                out_path=out,
                tournament_name=tournament_name,
                tournament_date=tournament_date,
                tournament_location=tournament_location,
                ranking=ranking,
            )
        except Exception as e:
            QMessageBox.critical(self, "Export PDF", f"Erreur: {e}")
            return

        QMessageBox.information(self, "Export PDF", f"PDF exporté:\n{out}")

    def _build_pdf(
        self,
        out_path: Path,
        tournament_name: str,
        tournament_date: str,
        tournament_location: str,
        ranking,
    ) -> None:
        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            str(out_path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=f"{tournament_name} - Classement",
        )

        story = []

        story.append(Paragraph(tournament_name, styles["Title"]))
        subtitle_parts = [p for p in [tournament_date, tournament_location] if p]
        if subtitle_parts:
            story.append(Paragraph(" — ".join(subtitle_parts), styles["Heading3"]))
        story.append(Spacer(1, 8 * mm))

        story.append(Paragraph("Classement Général", styles["Heading2"]))

        rank_rows = [["Rang", "Joueur", "Victoires", "Points gagnés", "Points perdus", "Goal Average"]]
        for i, s in enumerate(ranking, start=1):
            rank_rows.append([str(i), str(s.name), str(s.wins), str(s.plus), str(s.minus), str(s.ga)])

        t = Table(rank_rows, colWidths=[14 * mm, 78 * mm, 22 * mm, 26 * mm, 26 * mm, 26 * mm])
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1B4D8C")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 6 * mm))

        story.append(
            Paragraph(
                f"Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                styles["BodyText"],
            )
        )

        doc.build(story)