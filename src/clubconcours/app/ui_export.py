from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QFileDialog,
    QSpinBox,
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from clubconcours.core.ranking import compute_player_ranking


# ---- Friendly labels used in exports (same meaning as UI) ----
FORMAT_LABELS: dict[str, str] = {
    "SINGLE": "Tête-à-tête",
    "DOUBLETTE": "Doublette",
    "TRIPLETTE": "Triplette",
}

DRAW_MODE_LABELS: dict[str, str] = {
    "RANDOM": "Aléatoire",
    "AVOID_DUPLICATES": "Éviter les doublons",
    "SWISS_BY_WINS": "Suisse (par victoires)",
}


@dataclass
class ValidatedMatchLine:
    round_number: int
    match_id: int
    court_number: int | None
    team1: str
    team2: str | None  # None => exempt
    score1: int
    score2: int


class ExportTab(QWidget):
    data_changed = Signal()

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn

        layout = QVBoxLayout(self)

        title_row = QHBoxLayout()
        title = QLabel("Export PDF")
        title.setStyleSheet("font-weight: 700; font-size: 16px;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Partie à exporter (0 = toutes):"))
        self.spin_round = QSpinBox()
        self.spin_round.setMinimum(0)
        self.spin_round.setMaximum(999)
        self.spin_round.setValue(0)
        sel_row.addWidget(self.spin_round)
        sel_row.addStretch(1)
        layout.addLayout(sel_row)

        btn_row = QHBoxLayout()

        self.btn_rank_full = QPushButton("Exporter classement (complet)…")
        self.btn_rank_full.clicked.connect(self._export_ranking_full)
        btn_row.addWidget(self.btn_rank_full)

        self.btn_validated = QPushButton("Exporter parties validées…")
        self.btn_validated.clicked.connect(self._export_validated_rounds)
        btn_row.addWidget(self.btn_validated)

        self.btn_final = QPushButton("Exporter FINAL (tout)…")
        self.btn_final.clicked.connect(self._export_final)
        btn_row.addWidget(self.btn_final)

        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addWidget(
            QLabel(
                "Notes:\n"
                "- Parties validées = matchs avec validated=1.\n"
                "- Le classement est calculé uniquement sur les matchs validés."
            )
        )

    # ---------------- meta helpers ----------------

    def _meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _tournament_header(self) -> tuple[str, str, str]:
        name = self._meta_get("tournament_name") or "CLUBConcours"
        d = self._meta_get("tournament_date") or ""
        loc = self._meta_get("tournament_location") or ""
        return name, d, loc

    def _params_line(self) -> str:
        num_courts = self._meta_get("num_courts") or ""
        planned = self._meta_get("num_rounds_planned") or ""
        parts = []
        if num_courts:
            parts.append(f"Terrains: {num_courts}")
        if planned:
            parts.append(f"Parties prévues: {planned}")
        parts.append("Score: 13 points")
        parts.append("Exempt: 13–7")
        return " | ".join(parts)

    def _load_plan(self) -> list[dict]:
        plan_json = self._meta_get("round_plan_json") or ""
        if not plan_json:
            return []
        try:
            return json.loads(plan_json)
        except Exception:
            return []

    def _round_meta(self, round_number: int) -> tuple[str | None, str | None]:
        """
        Returns (format_code, draw_mode_code) from rounds table for a given round number.
        """
        r = self.conn.execute(
            "SELECT format, draw_mode FROM rounds WHERE number=?",
            (int(round_number),),
        ).fetchone()
        if r is None:
            return None, None
        fmt = r["format"]
        mode = r["draw_mode"]
        return (str(fmt) if fmt is not None else None, str(mode) if mode is not None else None)

    # ---------------- data extraction ----------------

    def _team_label(self, team_id: int) -> str:
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
        return " / ".join(str(r["name"]) for r in rows) or f"Team#{team_id}"

    def _validated_matches_lines(self, only_round_number: int | None) -> list[ValidatedMatchLine]:
        params: list = []
        where = "m.validated=1"
        if only_round_number is not None:
            where += " AND r.number=?"
            params.append(int(only_round_number))

        rows = self.conn.execute(
            f"""
            SELECT r.number AS round_number,
                   m.id AS match_id,
                   m.team1_id, m.team2_id,
                   m.score1, m.score2,
                   ca.court_number AS court_number
            FROM matches m
            JOIN rounds r ON r.id = m.round_id
            LEFT JOIN court_assignments ca ON ca.match_id = m.id
            WHERE {where}
            ORDER BY r.number, m.id
            """,
            tuple(params),
        ).fetchall()

        out: list[ValidatedMatchLine] = []
        for r in rows:
            rn = int(r["round_number"])
            mid = int(r["match_id"])
            t1 = int(r["team1_id"])
            t2 = r["team2_id"]
            s1 = int(r["score1"])
            s2 = int(r["score2"])
            court = r["court_number"]
            court_n = None if court is None else int(court)

            team1 = self._team_label(t1)
            team2 = None if t2 is None else self._team_label(int(t2))

            out.append(
                ValidatedMatchLine(
                    round_number=rn,
                    match_id=mid,
                    court_number=court_n,
                    team1=team1,
                    team2=team2,
                    score1=s1,
                    score2=s2,
                )
            )
        return out

    # ---------------- file picking ----------------

    def _pick_pdf_path(self, default_name: str) -> Path | None:
        filename, _ = QFileDialog.getSaveFileName(self, "Exporter en PDF", default_name, "PDF (*.pdf)")
        if not filename:
            return None
        out = Path(filename)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")
        return out

    # ---------------- PDF helpers ----------------

    def _make_doc(self, out_path: Path, title: str) -> SimpleDocTemplate:
        return SimpleDocTemplate(
            str(out_path),
            pagesize=A4,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
            title=title,
        )

    def _styles(self):
        styles = getSampleStyleSheet()

        styles.add(
            ParagraphStyle(
                name="Small",
                parent=styles["BodyText"],
                fontSize=9,
                leading=11,
            )
        )
        styles.add(ParagraphStyle(name="TitleCenter", parent=styles["Title"], alignment=1))
        styles.add(ParagraphStyle(name="H2Center", parent=styles["Heading2"], alignment=1))
        styles.add(ParagraphStyle(name="H3Center", parent=styles["Heading3"], alignment=1))
        styles.add(ParagraphStyle(name="SmallCenter", parent=styles["Small"], alignment=1))
        return styles

    def _table_style_header(self, bg_hex: str):
        return TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(bg_hex)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#B0B0B0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#E7E7E7")]),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )

    def _append_header(self, story: list, styles) -> None:
        name, d, loc = self._tournament_header()
        story.append(Paragraph(name, styles["TitleCenter"]))

        subtitle_parts = [p for p in [d, loc] if p]
        if subtitle_parts:
            story.append(Paragraph(" — ".join(subtitle_parts), styles["SmallCenter"]))

        story.append(Spacer(1, 6 * mm))

    def _append_params(self, story: list, styles) -> None:
        story.append(Paragraph(self._params_line(), styles["SmallCenter"]))
        story.append(Spacer(1, 6 * mm))

    def _append_plan(self, story: list, styles) -> None:
        plan = self._load_plan()
        story.append(Paragraph("Plan des parties", styles["H2Center"]))
        story.append(Spacer(1, 2 * mm))

        if not plan:
            story.append(Paragraph("(Aucun plan enregistré)", styles["SmallCenter"]))
            story.append(Spacer(1, 6 * mm))
            return

        rows = [["Partie", "Format", "Mode tirage"]]
        for r in plan:
            fmt_code = str(r.get("format", ""))
            mode_code = str(r.get("draw_mode", ""))
            fmt_lbl = FORMAT_LABELS.get(fmt_code, fmt_code)
            mode_lbl = DRAW_MODE_LABELS.get(mode_code, mode_code)
            rows.append([str(r.get("round_number", "")), fmt_lbl, mode_lbl])

        t = Table(rows, colWidths=[18 * mm, 52 * mm, 112 * mm], hAlign="CENTER")
        t.setStyle(self._table_style_header("#2F2F2F"))
        t.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("ALIGN", (1, 1), (1, -1), "CENTER"),
                    ("ALIGN", (2, 1), (2, -1), "CENTER"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 8 * mm))

    def _append_ranking(self, story: list, styles) -> None:
        ranking = compute_player_ranking(self.conn)
        story.append(Paragraph("Classement Général", styles["H2Center"]))
        story.append(Spacer(1, 2 * mm))

        rows = [["Rang", "Joueur", "Victoires", "Points gagnés", "Points perdus", "Goal Average"]]
        for i, s in enumerate(ranking, start=1):
            rows.append([str(i), str(s.name), str(s.wins), str(s.plus), str(s.minus), str(s.ga)])

        t = Table(rows, colWidths=[14 * mm, 78 * mm, 20 * mm, 26 * mm, 26 * mm, 26 * mm], hAlign="CENTER")
        t.setStyle(self._table_style_header("#1B4D8C"))
        t.setStyle(
            TableStyle(
                [
                    ("ALIGN", (0, 1), (0, -1), "CENTER"),
                    ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                    ("ALIGN", (1, 1), (1, -1), "LEFT"),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 6 * mm))

    def _append_validated_rounds(self, story: list, styles, only_round_number: int | None) -> None:
        lines = self._validated_matches_lines(only_round_number)

        story.append(Paragraph("Parties (matchs validés)", styles["H2Center"]))
        if only_round_number is not None:
            story.append(Paragraph(f"Filtre: Partie {only_round_number}", styles["SmallCenter"]))
        story.append(Spacer(1, 6 * mm))

        if not lines:
            story.append(Paragraph("Aucun match validé.", styles["SmallCenter"]))
            story.append(Spacer(1, 6 * mm))
            return

        current_rn = None
        block: list[ValidatedMatchLine] = []

        def flush_block() -> None:
            nonlocal block, current_rn
            if not block or current_rn is None:
                return

            # Round meta
            fmt_code, mode_code = self._round_meta(current_rn)
            fmt_lbl = FORMAT_LABELS.get(fmt_code or "", fmt_code or "")
            mode_lbl = DRAW_MODE_LABELS.get(mode_code or "", mode_code or "")

            story.append(Paragraph(f"Partie {current_rn}", styles["H3Center"]))
            if fmt_lbl or mode_lbl:
                story.append(Paragraph(f"{fmt_lbl}  |  {mode_lbl}", styles["SmallCenter"]))
            story.append(Spacer(1, 2 * mm))

            rows = [["Match", "Terrain", "Équipe 1", "Équipe 2", "Score"]]
            for m in block:
                court_txt = "" if m.court_number is None else str(m.court_number)
                score_txt = f"{m.score1}–{m.score2}"
                if m.team2 is None:
                    rows.append([str(m.match_id), court_txt, m.team1, "EXEMPT", score_txt])
                else:
                    rows.append([str(m.match_id), court_txt, m.team1, m.team2, score_txt])

            t = Table(rows, colWidths=[14 * mm, 16 * mm, 70 * mm, 70 * mm, 20 * mm], hAlign="CENTER")
            t.setStyle(self._table_style_header("#3A3A3A"))
            t.setStyle(
                TableStyle(
                    [
                        ("ALIGN", (0, 1), (1, -1), "CENTER"),
                        ("ALIGN", (4, 1), (4, -1), "CENTER"),
                        ("ALIGN", (2, 1), (3, -1), "LEFT"),
                        ("FONTSIZE", (0, 1), (-1, -1), 9),
                    ]
                )
            )
            story.append(t)
            story.append(Spacer(1, 8 * mm))

            block = []

        for m in lines:
            if current_rn != m.round_number:
                flush_block()
                current_rn = m.round_number
            block.append(m)
        flush_block()

    def _append_footer_generated(self, story: list, styles) -> None:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["SmallCenter"]))

    # ---------------- actions ----------------

    def _export_ranking_full(self) -> None:
        name, _, _ = self._tournament_header()
        out = self._pick_pdf_path(f"{name}_classement_complet.pdf".replace("/", "-").replace("\\", "-"))
        if out is None:
            return

        try:
            styles = self._styles()
            story: list = []
            doc = self._make_doc(out, f"{name} - Classement (complet)")

            self._append_header(story, styles)
            self._append_params(story, styles)
            self._append_plan(story, styles)
            self._append_ranking(story, styles)
            self._append_footer_generated(story, styles)

            doc.build(story)
        except Exception as e:
            QMessageBox.critical(self, "Export PDF", f"Erreur: {e}")
            return

        QMessageBox.information(self, "Export PDF", f"PDF exporté:\n{out}")

    def _export_validated_rounds(self) -> None:
        name, _, _ = self._tournament_header()
        only_rn = int(self.spin_round.value()) or None
        suffix = "toutes" if only_rn is None else f"partie_{only_rn}"
        out = self._pick_pdf_path(f"{name}_parties_validees_{suffix}.pdf".replace("/", "-").replace("\\", "-"))
        if out is None:
            return

        try:
            styles = self._styles()
            story: list = []
            doc = self._make_doc(out, f"{name} - Parties validées")

            self._append_header(story, styles)
            self._append_validated_rounds(story, styles, only_rn)
            self._append_footer_generated(story, styles)

            doc.build(story)
        except Exception as e:
            QMessageBox.critical(self, "Export PDF", f"Erreur: {e}")
            return

        QMessageBox.information(self, "Export PDF", f"PDF exporté:\n{out}")

    def _export_final(self) -> None:
        name, _, _ = self._tournament_header()
        only_rn = int(self.spin_round.value()) or None
        suffix = "toutes" if only_rn is None else f"partie_{only_rn}"
        out = self._pick_pdf_path(f"{name}_FINAL_{suffix}.pdf".replace("/", "-").replace("\\", "-"))
        if out is None:
            return

        try:
            styles = self._styles()
            story: list = []
            doc = self._make_doc(out, f"{name} - FINAL")

            self._append_header(story, styles)
            self._append_params(story, styles)
            self._append_plan(story, styles)

            story.append(PageBreak())
            self._append_validated_rounds(story, styles, only_rn)

            story.append(PageBreak())
            self._append_ranking(story, styles)

            self._append_footer_generated(story, styles)
            doc.build(story)
        except Exception as e:
            QMessageBox.critical(self, "Export PDF", f"Erreur: {e}")
            return

        QMessageBox.information(self, "Export PDF", f"PDF exporté:\n{out}")