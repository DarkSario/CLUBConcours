from __future__ import annotations

import json
import sqlite3

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QMessageBox,
    QFrame,
)

from clubconcours.core.draw import RoundConfig, draw_round
from clubconcours.storage.repositories import PlayerRepo

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

SWISS_STYLE_LABELS: dict[str, str] = {
    "STRONG": "Équipes fortes (proches ensemble)",
    "BALANCED": "Équipes équilibrées (fort + faible)",
}

SWISS_STYLE_HELP: dict[str, str] = {
    "STRONG": "Groupe les joueurs de niveau proche dans la même équipe (ex: 1-2, 3-4...). Matchs ensuite par niveau.",
    "BALANCED": "Constitue des équipes équilibrées (ex: 1 avec dernier, 2 avec avant-dernier...). Matchs ensuite par niveau.",
}


def _role_short(role: str) -> str:
    r = (role or "MIXTE").strip().upper()
    if r == "TIREUR":
        return "T"
    if r == "PLACEUR":
        return "P"
    return "M"


class DrawTab(QWidget):
    data_changed = Signal()
    round_created = Signal(int)  # round_id

    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.conn = conn
        self.player_repo = PlayerRepo(conn)

        self._edit_enabled = False

        layout = QVBoxLayout(self)

        # Dashboard card (summary)
        self.card = QFrame()
        self.card.setFrameShape(QFrame.StyledPanel)
        self.card.setStyleSheet("QFrame { background:#0B1220; border:1px solid #1F2937; border-radius:10px; }")
        card_l = QHBoxLayout(self.card)
        self.lbl_dash = QLabel("")
        self.lbl_dash.setStyleSheet("color:#9CA3AF;")
        card_l.addWidget(self.lbl_dash)
        card_l.addStretch(1)
        layout.addWidget(self.card)

        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["SINGLE", "DOUBLETTE", "TRIPLETTE"])
        row.addWidget(self.format_combo)

        row.addWidget(QLabel("Mode tirage:"))
        self.mode_combo = QComboBox()
        self._populate_mode_combo(self.mode_combo)
        self._set_mode_combo_by_code(self.mode_combo, "AVOID_DUPLICATES")
        row.addWidget(self.mode_combo)

        row.addWidget(QLabel("Suisse:"))
        self.swiss_style_combo = QComboBox()
        self._populate_swiss_style_combo(self.swiss_style_combo)
        self._set_swiss_style_by_code(self.swiss_style_combo, "STRONG")
        row.addWidget(self.swiss_style_combo)

        self.btn_modify = QPushButton("Modifier")
        self.btn_modify.clicked.connect(self._toggle_modify)
        row.addWidget(self.btn_modify)

        self.btn_draw = QPushButton("Tirer la partie")
        self.btn_draw.setProperty("primary", True)
        self.btn_draw.clicked.connect(self._draw)
        row.addWidget(self.btn_draw)

        row.addStretch(1)
        layout.addLayout(row)

        self.mode_help = QLabel("")
        self.mode_help.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(self.mode_help)

        self.swiss_help = QLabel("")
        self.swiss_help.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(self.swiss_help)

        self.mode_combo.currentIndexChanged.connect(self._update_help)
        self.swiss_style_combo.currentIndexChanged.connect(self._update_help)
        self._update_help()

        # Info line: shows what plan is being applied for next round
        self.plan_info = QLabel("")
        self.plan_info.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(self.plan_info)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        self._apply_edit_state()
        self.refresh()

    def _populate_mode_combo(self, combo: QComboBox) -> None:
        combo.clear()
        for code in ["AVOID_DUPLICATES", "SWISS_BY_WINS", "RANDOM"]:
            combo.addItem(DRAW_MODE_LABELS.get(code, code), code)
            combo.setItemData(combo.count() - 1, DRAW_MODE_HELP.get(code, ""), role=Qt.ToolTipRole)

    def _populate_swiss_style_combo(self, combo: QComboBox) -> None:
        combo.clear()
        for code in ["STRONG", "BALANCED"]:
            combo.addItem(SWISS_STYLE_LABELS.get(code, code), code)
            combo.setItemData(combo.count() - 1, SWISS_STYLE_HELP.get(code, ""), role=Qt.ToolTipRole)

    def _mode_code(self) -> str:
        code = self.mode_combo.currentData()
        return str(code) if code else "AVOID_DUPLICATES"

    def _swiss_style_code(self) -> str:
        code = self.swiss_style_combo.currentData()
        return str(code) if code else "STRONG"

    def _set_mode_combo_by_code(self, combo: QComboBox, code: str) -> None:
        idx = combo.findData(code)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _set_swiss_style_by_code(self, combo: QComboBox, code: str) -> None:
        idx = combo.findData(code)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _update_help(self) -> None:
        code = self._mode_code()
        self.mode_help.setText("Explication : " + DRAW_MODE_HELP.get(code, ""))

        swiss_code = self._swiss_style_code()
        self.swiss_help.setText("Suisse : " + SWISS_STYLE_HELP.get(swiss_code, ""))

        # combo always visible, enabled only when mode is swiss AND unlocked
        is_swiss = code == "SWISS_BY_WINS"
        self.swiss_style_combo.setEnabled(self._edit_enabled and is_swiss)

    def refresh(self) -> None:
        self._apply_edit_state()
        self._refresh_dashboard()
        if not self._edit_enabled:
            self._apply_plan_to_combos_for_next_round()

    def _apply_edit_state(self) -> None:
        self.format_combo.setEnabled(self._edit_enabled)
        self.mode_combo.setEnabled(self._edit_enabled)
        self.btn_modify.setText("Verrouiller" if self._edit_enabled else "Modifier")
        self._update_help()

    def _toggle_modify(self) -> None:
        self._edit_enabled = not self._edit_enabled
        self._apply_edit_state()
        if not self._edit_enabled:
            self._apply_plan_to_combos_for_next_round()

    def _next_round_number(self) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(number), 0) AS m FROM rounds").fetchone()
        return int(r["m"]) + 1

    def _previous_round_validated(self, round_number: int) -> bool:
        """
        Enforce strict sequential play: round N cannot be drawn until round N-1 is validated.
        Always-on (user requested mandatory).
        """
        if round_number <= 1:
            return True
        r = self.conn.execute(
            "SELECT validated FROM rounds WHERE number=?",
            (int(round_number - 1),),
        ).fetchone()
        if r is None:
            return False
        try:
            return int(r["validated"]) == 1
        except Exception:
            return False

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
            self._set_mode_combo_by_code(self.mode_combo, mode)

        code = self._mode_code()
        label = DRAW_MODE_LABELS.get(code, code)

        if fmt or mode:
            self.plan_info.setText(f"Plan concours: Partie {rn} → {fmt or '?'} / {label}")
        else:
            self.plan_info.setText(f"Plan concours: Partie {rn} → (pas de plan enregistré)")

        self._update_help()

    def _refresh_dashboard(self) -> None:
        try:
            n_players = int(self.conn.execute("SELECT COUNT(*) AS n FROM players WHERE active=1").fetchone()["n"])
        except Exception:
            # if migration not applied yet, fallback:
            try:
                n_players = int(self.conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()["n"])
            except Exception:
                n_players = 0

        try:
            n_rounds = int(self.conn.execute("SELECT COUNT(*) AS n FROM rounds").fetchone()["n"])
        except Exception:
            n_rounds = 0

        try:
            n_validated = int(self.conn.execute("SELECT COUNT(*) AS n FROM matches WHERE validated=1").fetchone()["n"])
        except Exception:
            n_validated = 0

        nxt = self._next_round_number()
        planned = self._num_rounds_planned()
        plan_txt = "?" if planned is None else str(planned)

        self.lbl_dash.setText(
            f"Joueurs actifs: {n_players}  |  Parties: {n_rounds}/{plan_txt}  |  Matchs validés: {n_validated}  |  Prochaine: {nxt}"
        )

    def _draw(self) -> None:
        if not self._contest_initialized():
            QMessageBox.warning(self, "Tirage", "Concours non initialisé (au démarrage).")
            return

        # IMPORTANT: only active players are drawn
        players = self.player_repo.list_players(active_only=True)
        if len(players) < 2:
            QMessageBox.warning(self, "Tirage", "Ajoute au moins 2 joueurs actifs.")
            return

        round_number = self._next_round_number()

        # Mandatory sequential validation: must validate N-1 before drawing N
        if not self._previous_round_validated(round_number):
            QMessageBox.warning(
                self,
                "Tirage",
                f"Impossible de tirer la partie {round_number} : la partie {round_number - 1} n'est pas validée.",
            )
            return

        planned = self._num_rounds_planned()
        if planned is not None and round_number > planned:
            QMessageBox.information(
                self,
                "Tirage",
                f"Le concours est prévu pour {planned} parties. Impossible de tirer la partie {round_number}.",
            )
            return

        if not self._edit_enabled:
            fmt, mode = self._get_plan_entry(round_number)
            if fmt:
                self.format_combo.setCurrentText(fmt)
            if mode:
                self._set_mode_combo_by_code(self.mode_combo, mode)

        fmt = self.format_combo.currentText()
        mode_code = self._mode_code()
        swiss_style = self._swiss_style_code()

        try:
            round_id = draw_round(
                self.conn,
                round_number=round_number,
                cfg=RoundConfig(format=fmt, draw_mode=mode_code, swiss_style=swiss_style),
                player_ids=[p.id for p in players],
            )
        except Exception as e:
            QMessageBox.critical(self, "Tirage", str(e))
            return

        self._edit_enabled = False
        self._apply_edit_state()

        self.output.setPlainText(self._format_round(round_id))
        self.data_changed.emit()
        self.round_created.emit(round_id)

        self._refresh_dashboard()
        self._apply_plan_to_combos_for_next_round()

    # ---------- role stats in output ----------

    def _role_stats_text(self, round_id: int) -> str:
        r = self.conn.execute("SELECT format FROM rounds WHERE id=?", (round_id,)).fetchone()
        fmt = str(r["format"]) if r else "?"

        rows = self.conn.execute(
            """
            SELECT rt.id AS team_id, p.role AS role
            FROM round_teams rt
            JOIN round_team_players rtp ON rtp.round_team_id = rt.id
            JOIN players p ON p.id = rtp.player_id
            WHERE rt.round_id=?
            ORDER BY rt.id
            """,
            (round_id,),
        ).fetchall()

        team_roles: dict[int, list[str]] = {}
        for rr in rows:
            tid = int(rr["team_id"])
            team_roles.setdefault(tid, []).append(str(rr["role"] or "MIXTE").upper())

        if fmt == "SINGLE":
            return "Rôles: (SINGLE) n/a"

        if fmt == "DOUBLETTE":
            tp = tm = pm = mm = tt = pp = 0
            for roles in team_roles.values():
                if len(roles) != 2:
                    continue
                s = set(roles)
                if "TIREUR" in s and "PLACEUR" in s:
                    tp += 1
                elif "TIREUR" in s and "MIXTE" in s:
                    tm += 1
                elif "PLACEUR" in s and "MIXTE" in s:
                    pm += 1
                elif s == {"MIXTE"}:
                    mm += 1
                elif s == {"TIREUR"}:
                    tt += 1
                elif s == {"PLACEUR"}:
                    pp += 1
            return f"Rôles équipes (DOUBLETTE): TP={tp}  TM={tm}  PM={pm}  MM={mm}  TT={tt}  PP={pp}"

        has_tp = t_only = p_only = all_m = 0
        for roles in team_roles.values():
            if len(roles) != 3:
                continue
            has_t = "TIREUR" in roles
            has_p = "PLACEUR" in roles
            if has_t and has_p:
                has_tp += 1
            elif has_t and not has_p:
                t_only += 1
            elif has_p and not has_t:
                p_only += 1
            else:
                all_m += 1

        return f"Rôles équipes (TRIPLETTE): has(T&P)={has_tp}  T_only={t_only}  P_only={p_only}  all_M={all_m}"

    # ---------- formatting output ----------

    def _format_round(self, round_id: int) -> str:
        r = self.conn.execute("SELECT * FROM rounds WHERE id=?", (round_id,)).fetchone()
        lines = [f"Round {r['number']} (id={round_id}) format={r['format']} mode={r['draw_mode']}"]

        lines.append(self._role_stats_text(round_id))

        teams = self.conn.execute(
            """
            SELECT rt.id AS team_id, rt.team_index, p.name, p.role
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
            nm = str(row["name"])
            rs = _role_short(str(row["role"] or "MIXTE"))
            team_map[tid]["players"].append(f"{nm} ({rs})")

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