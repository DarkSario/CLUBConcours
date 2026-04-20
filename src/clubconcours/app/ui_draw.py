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
    QComboBox,
    QPlainTextEdit,
    QMessageBox,
)

from clubconcours.core.draw import RoundConfig, draw_round
from clubconcours.storage.repositories import PlayerRepo


class DrawTab(QWidget):
    data_changed = Signal()
    round_created = Signal(int)  # round_id

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.player_repo = PlayerRepo(conn)

        self._edit_enabled = False

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["SINGLE", "DOUBLETTE", "TRIPLETTE"])
        row.addWidget(self.format_combo)

        row.addWidget(QLabel("Mode tirage:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["RANDOM", "AVOID_DUPLICATES", "SWISS_BY_WINS"])
        self.mode_combo.setCurrentText("AVOID_DUPLICATES")
        row.addWidget(self.mode_combo)

        self.btn_modify = QPushButton("Modifier")
        self.btn_modify.clicked.connect(self._toggle_modify)
        row.addWidget(self.btn_modify)

        self.btn_draw = QPushButton("Tirer la partie")
        self.btn_draw.clicked.connect(self._draw)
        row.addWidget(self.btn_draw)

        row.addStretch(1)
        layout.addLayout(row)

        # Info line: shows what plan is being applied for next round
        self.plan_info = QLabel("")
        layout.addWidget(self.plan_info)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        self._apply_edit_state()
        self.refresh()

    def refresh(self) -> None:
        # If user did not unlock "Modifier", keep UI in sync with concours plan
        self._apply_edit_state()
        if not self._edit_enabled:
            self._apply_plan_to_combos_for_next_round()

    def _apply_edit_state(self) -> None:
        self.format_combo.setEnabled(self._edit_enabled)
        self.mode_combo.setEnabled(self._edit_enabled)
        self.btn_modify.setText("Verrouiller" if self._edit_enabled else "Modifier")

    def _toggle_modify(self) -> None:
        self._edit_enabled = not self._edit_enabled
        self._apply_edit_state()
        if not self._edit_enabled:
            # When re-locking, snap back to plan for the next round
            self._apply_plan_to_combos_for_next_round()

    def _next_round_number(self) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(number), 0) AS m FROM rounds").fetchone()
        return int(r["m"]) + 1

    def _meta_get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def _contest_initialized(self) -> bool:
        return self._meta_get("contest_initialized") == "1"

    def _num_rounds_planned(self) -> int | None:
        v = self._meta_get("num_rounds_planned")
        if not v:
            return None
        try:
            return int(v)
        except Exception:
            return None

    def _get_plan_entry(self, round_number: int) -> tuple[str | None, str | None]:
        plan_json = self._meta_get("round_plan_json")
        if not plan_json:
            return None, None
        try:
            plan = json.loads(plan_json)
        except Exception:
            return None, None

        idx = round_number - 1
        if idx < 0 or idx >= len(plan):
            return None, None

        fmt = plan[idx].get("format")
        mode = plan[idx].get("draw_mode")
        return (fmt if isinstance(fmt, str) else None, mode if isinstance(mode, str) else None)

    def _apply_plan_to_combos_for_next_round(self) -> None:
        rn = self._next_round_number()
        fmt, mode = self._get_plan_entry(rn)

        if fmt:
            self.format_combo.setCurrentText(fmt)
        if mode:
            self.mode_combo.setCurrentText(mode)

        if fmt or mode:
            self.plan_info.setText(f"Plan concours: Partie {rn} → {fmt or '?'} / {mode or '?'}")
        else:
            self.plan_info.setText(f"Plan concours: Partie {rn} → (pas de plan enregistré)")

    def _draw(self) -> None:
        if not self._contest_initialized():
            QMessageBox.warning(self, "Tirage", "Concours non initialisé (au démarrage).")
            return

        players = self.player_repo.list_players()
        if len(players) < 2:
            QMessageBox.warning(self, "Tirage", "Ajoute au moins 2 joueurs.")
            return

        round_number = self._next_round_number()

        planned = self._num_rounds_planned()
        if planned is not None and round_number > planned:
            QMessageBox.information(
                self,
                "Tirage",
                f"Le concours est prévu pour {planned} parties. Impossible de tirer la partie {round_number}.",
            )
            return

        # Apply plan at click-time unless user unlocked Modify
        if not self._edit_enabled:
            fmt, mode = self._get_plan_entry(round_number)
            if fmt:
                self.format_combo.setCurrentText(fmt)
            if mode:
                self.mode_combo.setCurrentText(mode)

        fmt = self.format_combo.currentText()
        mode = self.mode_combo.currentText()

        try:
            round_id = draw_round(
                self.conn,
                round_number=round_number,
                cfg=RoundConfig(format=fmt, draw_mode=mode),
                player_ids=[p.id for p in players],
            )
        except Exception as e:
            QMessageBox.critical(self, "Tirage", str(e))
            return

        # after a draw, lock editing again (so next round uses plan by default)
        self._edit_enabled = False
        self._apply_edit_state()

        self.output.setPlainText(self._format_round(round_id))
        self.data_changed.emit()
        self.round_created.emit(round_id)

        # update info for next round
        self._apply_plan_to_combos_for_next_round()

    def _format_round(self, round_id: int) -> str:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
        lines = [f"Round {r['number']} (id={round_id}) format={r['format']} mode={r['draw_mode']}"]

        teams = self.conn.execute(
            """
            SELECT rt.id AS team_id, rt.team_index, p.name
            FROM round_teams rt
            JOIN round_team_players rtp ON rtp.round_team_id = rt.id
            JOIN players p ON p.id = rtp.player_id
            WHERE rt.round_id=?
            ORDER BY rt.team_index, p.name
            """,
            (round_id,),
        ).fetchall()

        team_map: dict[int, dict] = {}
        for row in teams:
            tid = int(row["team_id"])
            team_map.setdefault(tid, {"idx": int(row["team_index"]), "players": []})
            team_map[tid]["players"].append(str(row["name"]))

        lines.append("")
        for tid, info in sorted(team_map.items(), key=lambda kv: kv[1]["idx"]):
            lines.append(f"Team {info['idx']:>2}: {', '.join(info['players'])}")

        matches = self.conn.execute(
            """
            SELECT m.id, m.team1_id, m.team2_id, m.score1, m.score2
            FROM matches m
            WHERE m.round_id=?
            ORDER BY m.id
            """,
            (round_id,),
        ).fetchall()

        lines.append("")
        lines.append("Matchs:")
        for m in matches:
            t1 = int(m["team1_id"])
            t2 = m["team2_id"]
            s1 = m["score1"]
            s2 = m["score2"]

            if t2 is None:
                lines.append(f"- match {m['id']}: team {team_map[t1]['idx']} EXEMPT score={s1}-{s2}")
            else:
                lines.append(
                    f"- match {m['id']}: team {team_map[t1]['idx']} vs team {team_map[int(t2)]['idx']} score={s1}-{s2}"
                )

        return "\n".join(lines)