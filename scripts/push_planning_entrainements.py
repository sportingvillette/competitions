"""Met à jour automatiquement le tableau de planning des entraînements sur la page SportsRégions
"Planning entrainements" (admin.sportsregions.fr/page/edit/57258), en réutilisant
`renderEquipeMinimal(merged)` — déjà la fonction JS existante pour la version "à coller sur le
site" du planning (index.html, ce même repo).

Ne touche QUE la partie générée du champ (légende des couleurs + tableau) — le texte d'intro
écrit à la main par Julien juste au-dessus (titre "Créneaux", avertissements, lieu par défaut)
est préservé tel quel, relu à chaque run depuis la page en direct (jamais figé en dur dans ce
script), pour ne jamais écraser une modification manuelle faite entre 2 runs.

Testé le 2026-08-18 : les commentaires HTML (<!-- -->) ne survivent PAS à un cycle
sauvegarde/rechargement sur ce champ CKEditor (filtrés côté serveur) — donc pas de marqueur
caché possible. La frontière intro/généré est retrouvée par position : le dernier <p> ouvrant
avant le <table> (= la légende de couleurs, toujours immédiatement suivie du tableau dans la
sortie de renderEquipeMinimal — voir split_intro_and_generated). Si cette structure change un
jour côté page (intro restructurée), le script s'arrête avec une erreur claire plutôt que de
deviner.

Enchaîné automatiquement à la fin de `push_sportsregions_fiches.py` (lot complet uniquement,
pas en --dry-run ni --team) via `push_planning(page, site_url)`, qui réutilise le navigateur/la
session déjà ouverts par ce script-là plutôt que d'en relancer un second.

Usage autonome :
    python push_planning_entrainements.py --dry-run   # génère et affiche (intro + tableau), ne pousse rien (mais se connecte quand même, en lecture seule, pour lire l'intro actuel)
    python push_planning_entrainements.py               # pousse pour de vrai (connexion fraîche systématique)
    python push_planning_entrainements.py --headed      # navigateur visible
"""

from __future__ import annotations

import argparse
import sys

from playwright.sync_api import sync_playwright, Page

from sportsregions_pipeline import admin_bridge, ensure_logged_in, get_credentials, login

SITE_URL = "https://sportingvillette.github.io/competitions/"
PAGE_ID = "57258"

GENERATE_JS = """
    async () => {
      const csvText = await fetchCSV();
      const rows = parseCSV(csvText);
      const records = buildRecords(rows);
      const merged = mergeRecords(records);
      return renderEquipeMinimal(merged);
    }
"""


def generate_planning_html(page: Page, site_url: str) -> str:
    page.goto(site_url)
    page.wait_for_load_state("networkidle")
    return page.evaluate(GENERATE_JS)


def split_intro_and_generated(current_html: str) -> tuple[str, str]:
    """Coupe le HTML actuel du champ en (intro à préserver, partie générée à remplacer)."""
    table_idx = current_html.find("<table")
    if table_idx == -1:
        raise RuntimeError("Aucun <table> trouvé dans le contenu actuel de la page — structure inattendue, arrêt par prudence.")
    p_idx = current_html.rfind("<p", 0, table_idx)
    if p_idx == -1:
        raise RuntimeError("Aucun <p> trouvé avant le <table> — impossible de délimiter intro/généré, arrêt par prudence.")
    return current_html[:p_idx], current_html[p_idx:]


def push_planning(page: Page, site_url: str = SITE_URL, *, dry_run: bool = False) -> dict:
    """Point d'entrée réutilisable : met à jour (ou juste prévisualise si dry_run) la page
    "Planning entrainements" en utilisant une page Playwright déjà authentifiée (session
    SportsRégions valide sur ce `page`/son contexte). Ne gère PAS le lancement du navigateur ni
    la connexion — c'est la responsabilité de l'appelant (voir `main()` ci-dessous pour l'usage
    autonome, ou `push_sportsregions_fiches.py` pour l'usage enchaîné)."""
    new_generated = generate_planning_html(page, site_url)

    page.goto(admin_bridge(f"/page/edit/{PAGE_ID}"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    page.wait_for_selector("#ckeditor_contenu", state="attached")
    page.wait_for_function("window.CKEDITOR && window.CKEDITOR.instances['ckeditor_contenu']")
    page.wait_for_timeout(500)
    current = page.evaluate("window.CKEDITOR.instances['ckeditor_contenu'].getData()")

    intro, old_generated = split_intro_and_generated(current)

    if dry_run:
        return {"dry_run": True, "intro": intro, "old_generated": old_generated, "new_generated": new_generated}

    new_content = intro + new_generated
    page.evaluate(
        "([html]) => window.CKEDITOR.instances['ckeditor_contenu'].setData(html)",
        [new_content],
    )
    page.click("input.enregistrer")
    page.wait_for_load_state("networkidle")
    return {"dry_run": False, "updated": True}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="Génère et affiche (intro préservé + nouveau tableau), ne pousse rien (mais se connecte quand même, en lecture seule, pour lire l'intro actuel de la page)")
    ap.add_argument("--site", default=SITE_URL, help="URL du site à charger pour générer le tableau (défaut : GitHub Pages en prod)")
    ap.add_argument("--headed", action="store_true", help="Navigateur visible")
    args = ap.parse_args()

    if not get_credentials():
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

        login(page)

        result = push_planning(page, args.site, dry_run=args.dry_run)

        if result["dry_run"]:
            print("===== INTRO PRÉSERVÉ (inchangé) =====")
            print(result["intro"])
            print("===== ANCIEN TABLEAU (sera remplacé) =====")
            print(result["old_generated"])
            print("===== NOUVEAU TABLEAU GÉNÉRÉ =====")
            print(result["new_generated"])
        else:
            print('>>> Page "Planning entrainements" mise à jour.', file=sys.stderr)

        browser.close()


if __name__ == "__main__":
    main()
