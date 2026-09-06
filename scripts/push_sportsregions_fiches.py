"""Pousse le contenu de `renderEquipeFicheSportsRegions(r, classementsRows)` (fonction JS déjà
existante dans index.html, ce même repo) sur les fiches équipe SportsRégions déjà créées, une
par une. Enchaîne ensuite la mise à jour du planning entraînements (voir
push_planning_entrainements.py) sur un lot complet.

Point d'entrée unique pour tout le contenu SportsRégions généré depuis ce repo — utilisable
localement (identifiants via variables d'environnement, voir sportsregions_pipeline.py) ou
depuis le workflow GitHub Actions .github/workflows/update-sportsregions.yml (déclenché
manuellement par un bouton sur le site, voir index.html).

Ne réimplémente PAS la logique de rendu en Python : on charge le site GitHub Pages en direct
(same-origin, pas de souci CORS/file://, voir CLAUDE.md du repo) dans une page Playwright et on
appelle directement les fonctions JS existantes (fetchCSV, parseCSV, buildRecords,
renderEquipeFicheSportsRegions) via page.evaluate — la seule source de vérité du rendu reste
index.html, ce script se contente de récupérer le HTML généré et de le pousser équipe par
équipe via les briques de sportsregions_pipeline.py (find_team_id, update_team_content).

Se connecte systématiquement avec une session fraîche à chaque run (pas de persistance de
session entre exécutions — inutile en CI où chaque run est une VM neuve, et évite le piège de
réutiliser une session périmée/cassée constaté le 2026-08-18, voir sportsregions_pipeline.py).

Usage :
    python push_sportsregions_fiches.py --dry-run              # génère et affiche tout, ne pousse rien (pas de login)
    python push_sportsregions_fiches.py --dry-run --team "M16F A"
    python push_sportsregions_fiches.py --team "M16F A"         # pousse une seule équipe (test avant lot complet)
    python push_sportsregions_fiches.py                         # pousse toutes les équipes + planning entraînements
    python push_sportsregions_fiches.py --headed                # navigateur visible (vérif visuelle)

`--team` attend le nom SportsRégions exact tel que déjà créé (convention {Catégorie}{Genre}
{Indice}, ex. "M16F A", "SF A" pour Seniors — voir CLAUDE.md du repo, section "Automatisation
SportsRégions").

Sur un lot complet (ni --dry-run ni --team), enchaîne en fin de run la mise à jour de la page
"Planning entrainements" (push_planning_entrainements.py, même navigateur/session déjà ouverts,
pas de second login) : les deux automatisations de contenu SportsRégions restent un seul point
d'entrée à exécuter/programmer, plutôt que deux tâches séparées à garder synchronisées (demande
explicite de Julien, 2026-08-18).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright, Page

from sportsregions_pipeline import (
    SAISON_VALUES,
    SECTION_VALUES,
    find_team_id,
    get_credentials,
    login,
    update_team_content,
)
from push_planning_entrainements import push_planning
from push_calendriers_classements import push_calendriers_classements

SITE_URL = "https://sportingvillette.github.io/competitions/"
SAISON = "2026-2027"

GENERATE_JS = """
    async () => {
      const csvText = await fetchCSV();
      const rows = parseCSV(csvText);
      const records = buildRecords(rows);
      const clText = await fetchText(CLASSEMENTS_CLUB_URL);
      const classementsRows = parseCSV(clText);
      return records.map(r => ({
        section: r.section, categorie: r.categorie, genre: r.genre, indice: r.indice,
        html: renderEquipeFicheSportsRegions(r, classementsRows),
      }));
    }
"""


# Catégorie du CSV -> catégorie telle qu'utilisée dans le nom d'équipe SportsRégions, pour les
# cas où les deux divergent (constaté le 2026-08-17 : Sheet "Loisirs", site "Loisir" — le nom
# sur SportsRégions n'a pas été renommé en même temps que la colonne Categorie du Sheet).
CATEGORIE_OVERRIDES = {
    "Seniors": "S",
    "Loisirs": "Loisir",
}


def sportsregions_team_name(categorie: str, genre: str, indice: str | None) -> str:
    """{Catégorie}{Genre} {Indice} — genre accolé sans espace, indice séparé par un espace,
    "Seniors" abrégé en "S" (convention documentée dans CLAUDE.md du repo). Voir
    CATEGORIE_OVERRIDES pour les catégories dont le nom diverge entre Sheet et SportsRégions."""
    cat = CATEGORIE_OVERRIDES.get(categorie, categorie)
    g = genre if genre in ("F", "G") else ""
    name = cat + g
    if indice:
        name += " " + indice
    return name


def generate_fiches(page: Page, site_url: str) -> list[dict]:
    page.goto(site_url)
    page.wait_for_load_state("networkidle")
    return page.evaluate(GENERATE_JS)


_RUN_STARTED_AT = None


def post_progress(team_index=0, team_total=0, team_label="", done=False, error=None):
    """Remonte une progression au Web App Apps Script (action `progress_sportsregions`,
    même mécanisme de CacheService que le scraper FFHB — voir CLAUDE.md du repo, section
    "Barre de progression"). Best-effort, ne doit jamais faire échouer le run : sans effet si
    SHEET_WEBAPP_URL/SHEET_WEBAPP_SECRET absentes (ex. run local sans ces variables définies)."""
    url = os.environ.get("SHEET_WEBAPP_URL", "").strip()
    secret = os.environ.get("SHEET_WEBAPP_SECRET", "").strip()
    if not url or not secret or not _RUN_STARTED_AT:
        return
    payload = {
        "secret": secret,
        "action": "progress_sportsregions",
        "progress": {
            "started_at": _RUN_STARTED_AT,
            "team_index": team_index,
            "team_total": team_total,
            "team_label": team_label,
            "done": done,
            "error": error,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Génère et affiche le HTML de chaque équipe, ne pousse rien (pas de connexion SportsRégions)")
    ap.add_argument("--team", help="Nom SportsRégions exact d'une seule équipe à traiter, ex. 'M16F A'")
    ap.add_argument("--headed", action="store_true", help="Navigateur visible")
    ap.add_argument("--site", default=SITE_URL, help="URL du site à charger (défaut : GitHub Pages en prod ; utiliser un serveur local pour tester une modif pas encore mergée sur main)")
    args = ap.parse_args()

    if not args.dry_run and not get_credentials():
        print(
            "!!! Identifiants SportsRégions absents : variables d'environnement "
            "SPORTSREGIONS_USERNAME / SPORTSREGIONS_PASSWORD non définies.",
            file=sys.stderr,
        )
        sys.exit(1)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context()
        page = context.new_page()

        if not args.dry_run:
            login(page)

        fiches = generate_fiches(page, args.site)
        print(f">>> {len(fiches)} fiche(s) générée(s) depuis le site.", file=sys.stderr)

        targets = []
        for r in fiches:
            name = sportsregions_team_name(r["categorie"], r["genre"], r["indice"])
            if args.team and name != args.team:
                continue
            targets.append((name, r))

        if args.team and not targets:
            print(f"!!! Aucune équipe du CSV ne correspond à --team '{args.team}'.", file=sys.stderr)
            sys.exit(1)

        if args.dry_run:
            for name, r in targets:
                print(f"===== {name} ({r['section']}) =====")
                print(r["html"])
                print()
            browser.close()
            return

        global _RUN_STARTED_AT
        _RUN_STARTED_AT = datetime.datetime.now(datetime.timezone.utc).isoformat()
        # +2 unités : planning entraînements + page calendriers/classements, poussées après les
        # fiches (voir plus bas).
        progress_total = len(targets) + 2
        post_progress(0, progress_total, "")

        saison_value = SAISON_VALUES[SAISON]
        ok, fail = 0, []
        for i, (name, r) in enumerate(targets):
            post_progress(i + 1, progress_total, name)
            # find_team_id ET update_team_content dans le même try : les deux font des
            # page.goto, donc les deux peuvent subir un timeout réseau transitoire (constaté le
            # 2026-08-18, net::ERR_TIMED_OUT en plein lot) — un échec sur l'un ou l'autre doit
            # sauter cette équipe et continuer le lot, jamais faire planter tout le script. 1
            # retry après une courte pause avant d'abandonner (même pattern que la flakiness
            # Apps Script déjà documentée dans CLAUDE.md du repo).
            last_error = None
            updated = False
            for attempt in range(2):
                try:
                    team_id = find_team_id(page, name)
                    if not team_id:
                        last_error = "introuvable sur SportsRégions"
                        break  # pas la peine de retenter, ce n'est pas une flakiness réseau
                    update_team_content(
                        page,
                        team_id,
                        presentation_html=r["html"],
                        section_value=SECTION_VALUES[r["section"]],
                        saison_value=saison_value,
                    )
                    updated = True
                    break
                except Exception as e:
                    last_error = str(e)
                    if attempt == 0:
                        page.wait_for_timeout(2_000)

            if updated:
                ok += 1
                print(f">>> {name} mise à jour.", file=sys.stderr)
            else:
                print(f"!!! Échec sur '{name}' : {last_error}", file=sys.stderr)
                fail.append(name)

        summary = f">>> Terminé : {ok} mise(s) à jour, {len(fail)} échec(s)"
        if fail:
            summary += " (" + ", ".join(fail) + ")"
        print(summary + ".", file=sys.stderr)

        # Lot complet uniquement (pas --team) : enchaîne la mise à jour du planning
        # entraînements puis de la page calendriers/résultats/classements, même
        # navigateur/session déjà authentifiés (demande de Julien, 2026-08-18/20 — un seul
        # point d'entrée pour tout le contenu SportsRégions généré).
        extra_errors = []
        if not args.team:
            post_progress(len(targets) + 1, progress_total, "Planning entraînements")
            try:
                push_planning(page, args.site)
                print('>>> Page "Planning entrainements" mise à jour.', file=sys.stderr)
            except Exception as e:
                extra_errors.append(f"planning: {e}")
                print(f'!!! Échec de la mise à jour du planning entraînements : {e}', file=sys.stderr)

            post_progress(len(targets) + 2, progress_total, "Calendriers, résultats, classements")
            try:
                push_calendriers_classements(page, args.site)
                print('>>> Page "Calendriers, résultats, classements" mise à jour.', file=sys.stderr)
            except Exception as e:
                extra_errors.append(f"calendriers/classements: {e}")
                print(f'!!! Échec de la mise à jour de la page calendriers/classements : {e}', file=sys.stderr)

        post_progress(
            progress_total, progress_total, "", done=True,
            error=", ".join(fail + extra_errors) or None,
        )

        browser.close()


if __name__ == "__main__":
    main()
