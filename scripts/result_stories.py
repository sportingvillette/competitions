#!/usr/bin/env python3
"""Trouve les matchs prêts pour une story résultat (score final + photo
officielle disponibles, pas déjà générée), et marque un match comme traité
une fois sa story générée.

Source de données : le CSV publié du Google Sheet "Com matchs réseaux",
onglet "Matchs" (mêmes colonnes que `apps-script/Code.gs`, voir CLAUDE.md
section "Colonnes de la sheet Matchs"). Réutilise le même Web App Apps
Script que `form-score-club-2-` pour marquer un match traité (action
`mark_story_done`, ajoutée le 2026-08-17) — mêmes URL/secret publics que
ceux déjà embarqués en clair dans le JS public de ce formulaire (voir
Code.gs, en-tête : FORM_SHARED_SECRET est délibérément moins sensible que
SHARED_SECRET, sa présence ici ne constitue pas une nouvelle exposition).

Usage :
    python scripts/result_stories.py list [--out fichier.json] [--window-only]
    python scripts/result_stories.py mark-done --match-id rencontre-XXXXXXX [--value texte]

`list` n'affiche QUE les matchs avec score final + `PhotoEq` renseignés ET
`Story résultat` encore vide — "pas de photo -> pas de story", point. La
règle est appliquée ici, pas laissée à l'appréciation de qui lit la sortie.
Les tournois M7/M9 (Journée "Tournoi N", pas de score compté) sont exclus.

Plus aucune restriction horaire (2026-11-15, demande de Julien : la tâche est
désormais lancée surtout à la main, à n'importe quelle heure). Avant, `--window-only`
faisait refuser tout travail hors du samedi 12h-23h / dimanche 11h-17h (heure de Paris).
L'option est conservée UNIQUEMENT pour qu'un ancien prompt de tâche qui la passe encore
ne plante pas : elle est ignorée (avertissement sur stderr).
"""

import argparse
import csv
import io
import json
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

MATCHS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQvskuueB25qKj0hbDWjFPomFdhfWRduUsNLp6Kv-za4t4oXcbbLsLrNsjwIt0ZH7C9B75pYBGDJfQu/"
    "pub?output=csv"
)
# Mêmes valeurs que CONFIG.webhookUrl / CONFIG.webhookSecret dans
# form-score-club-2-/index.html (public, voir docstring ci-dessus).
WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbzA8_vH6hAwZl3aBOxEtL4sKqxi10mhY6Tw0dDRLU-SHszHHui4GXSR04GX8VV15oQC/exec"
FORM_SHARED_SECRET = "wpFt6IaS4QDZCodB"


def _read_csv(url: str) -> list:
    with urllib.request.urlopen(url, timeout=30) as resp:
        raw = resp.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(raw)))


def equipe_label(categorie: str, genre: str, indice: str) -> str:
    """'M15', 'G', 'A' -> 'M15G A' (catégorie+genre collés, indice séparé
    par un espace) — même convention que le gabarit Canva DAHS8CDDMvk."""
    base = f"{categorie}{genre}" if genre else categorie
    return f"{base} {indice}" if indice else base


def find_eligible(rows: list) -> list:
    eligible = []
    for r in rows:
        eq1score = (r.get("Eq1Score", "") or "").strip()
        eq2score = (r.get("Eq2Score", "") or "").strip()
        winlose = (r.get("WinLose", "") or "").strip()
        photo = (r.get("PhotoEq", "") or "").strip()
        already_done = (r.get("Story résultat", "") or "").strip()
        match_id = (r.get("Code Gesthand", "") or "").strip()

        if not (eq1score and eq2score and winlose):
            continue  # pas encore de score final
        if not photo:
            continue  # pas de photo -> pas de story, point
        if already_done:
            continue  # déjà traité
        if not match_id:
            continue  # pas d'identifiant fiable pour marquer le match ensuite
        if (r.get("Journée", "") or "").strip().casefold().startswith("tournoi"):
            # Tournoi M7/M9 : on ne compte pas le score. Le formulaire du club enregistre quand même
            # un "0 - 0 / Match Nul" quand on y ajoute la photo (constaté le 2026-11-15 sur les
            # tournois M9 du 7 novembre) : sans cette exclusion, une story "Match nul 0-0"
            # serait générée pour un plateau.
            continue

        eligible.append({
            "match_id": match_id,
            "equipe": equipe_label(
                (r.get("Catégorie", "") or "").strip(),
                (r.get("Genre", "") or "").strip(),
                (r.get("Index", "") or "").strip(),
            ),
            "championnat": (r.get("Championnat", "") or "").strip(),
            "date": (r.get("Date", "") or "").strip(),
            "heure": (r.get("Heure", "") or "").strip(),
            "eq1": (r.get("Eq1", "") or "").strip(),
            "eq2": (r.get("Eq2", "") or "").strip(),
            "eq1score": eq1score,
            "eq2score": eq2score,
            "winlose": winlose,
            "photo_url": photo,
        })
    return eligible


def mark_done(match_id: str, value: str = "") -> dict:
    data = urllib.parse.urlencode({
        "action": "mark_story_done",
        "secret": FORM_SHARED_SECRET,
        "match_id": match_id,
        "value": value or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }).encode("utf-8")
    req = urllib.request.Request(WEBHOOK_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Liste les matchs prêts pour une story résultat")
    p_list.add_argument("--matchs", default=MATCHS_CSV_URL, help="URL du CSV publié de la sheet Matchs")
    p_list.add_argument("--out", default="-", help="Fichier de sortie JSON ('-' = stdout)")
    p_list.add_argument(
        "--window-only", action="store_true",
        help="OBSOLÈTE, ignoré : il n'y a plus de restriction horaire (conservé pour qu'un "
             "ancien prompt qui le passe encore ne plante pas).",
    )

    p_mark = sub.add_parser("mark-done", help="Marque un match comme ayant sa story générée")
    p_mark.add_argument("--match-id", required=True)
    p_mark.add_argument("--value", default="", help="Valeur à écrire (défaut : horodatage ISO UTC)")

    args = ap.parse_args()

    if args.command == "list":
        if args.window_only:
            print("--window-only est obsolète et ignoré (plus de restriction horaire).", file=sys.stderr)

        rows = _read_csv(args.matchs)
        eligible = find_eligible(rows)
        out_text = json.dumps({"matches": eligible}, ensure_ascii=False, indent=2)
        if args.out == "-":
            print(out_text)
        else:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(out_text)
        print(f"{len(eligible)} match(s) éligible(s).", file=sys.stderr)

    elif args.command == "mark-done":
        result = mark_done(args.match_id, args.value)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            sys.exit(1)


if __name__ == "__main__":
    main()
