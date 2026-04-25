from __future__ import annotations

from pathlib import Path

from clubconcours.core.draw import RoundConfig, draw_round
from clubconcours.core.ranking import compute_player_ranking
from clubconcours.storage import db
from clubconcours.storage.repositories import PlayerRepo, RoundRepo
from clubconcours.app.inspect_round import print_round

NAMES = [
    "Alice", "Bob", "Chloé", "David",
    "Emma", "Fabien", "Gaby", "Hugo",
    "Inès", "Julien", "Karim", "Léa",
    "Mehdi",
]

def main() -> None:
    db_path = Path(db.default_db_filename("CLUBConcours"))
    print("DB:", db_path)

    conn = db.connect(str(db_path))
    db.init_db(conn)

    pr = PlayerRepo(conn)
    rr = RoundRepo(conn)

    pr.add_players(NAMES)
    players = pr.list_players()
    player_ids = [p.id for p in players]
    print(f"Players: {len(player_ids)}")

    # Round 1
    r1 = draw_round(
        conn,
        round_number=1,
        cfg=RoundConfig(format="DOUBLETTE", draw_mode="AVOID_DUPLICATES"),
        player_ids=player_ids,
    )
    print("Round1 id:", r1)

    # Set fake scores for non-exempt matches
    matches = conn.execute(
        "SELECT id, team2_id FROM matches WHERE round_id=? ORDER BY id",
        (r1,),
    ).fetchall()
    for m in matches:
        mid = int(m["id"])
        if m["team2_id"] is None:
            continue  # exempt already prefilled if configured
        rr.set_match_score(mid, 13, 9)

    rr.validate_round(r1)

    print("\nRanking after round 1:")
    for s in compute_player_ranking(conn):
        print(f"- {s.name:10} wins={s.wins} plus={s.plus} minus={s.minus} ga={s.ga}")

    # Round 2 (choose the mode here)
    r2 = draw_round(
        conn,
        round_number=2,
        cfg=RoundConfig(format="DOUBLETTE", draw_mode="SWISS_BY_WINS"),
        player_ids=player_ids,
    )
    print("\nRound2 id:", r2)
    print_round(conn, r2)
    print("Done (scores not entered yet).")

if __name__ == "__main__":
    main()