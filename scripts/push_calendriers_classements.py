"""Met à jour automatiquement la page SportsRégions "Calendriers, résultats, classements"
(admin.sportsregions.fr/page/edit/109233), en réutilisant `renderCalendriersClassementsPage`
— fonction JS existante dans index.html, ce même repo.

Construite uniquement à partir de scraper/team_mapping.csv et data/classements_club.csv
(pas besoin du CSV équipes) : pour chaque équipe+phase déjà connue du scraper, une ligne avec
son niveau, un lien vers sa poule FFHB, et sa position dans le classement de sa poule
(quand identifiable — même limite "club porteur" que le reste du site, voir CLAUDE.md).

Ne touche QUE la partie générée du champ (le tableau) — le titre écrit à la main au-dessus
("Liens vers les classements et résultats") est préservé tel quel, relu à chaque run depuis
la page en direct (même principe que push_planning_entrainements.py, voir
split_intro_and_generated).

Enchaîné automatiquement à la fin de `push_sportsregions_fiches.py` (lot complet uniquement,
pas en --dry-run ni --team) via `push_calendriers_classements(page, site_url)`, qui réutilise
le navigateur/la session déjà ouverts par ce script-là plutôt que d'en relancer un second.

Usage autonome :
    python push_calendriers_classements.py --dry-run   # génère et affiche (intro + tableau), ne pousse rien (mais se connecte quand même, en lecture seule, pour lire l'intro actuel)
    python push_calendriers_classements.py               # pousse pour de vrai (connexion fraîche systématique)
    python push_calendriers_classements.py --headed      # navigateur visible
"""

from __future__ import annotations

import argparse
import sys

from playwright.sync_api import sync_playwright, Page

from sportsregions_pipeline import admin_bridge, ensure_logged_in, get_credentials, login

SITE_URL = "https://sportingvillette.github.io/competitions/"
PAGE_ID = "109233"

GENERATE_JS = """
    async () => {
      const [mapText, clText, calText] = await Promise.all([
        fetchText(TEAM_MAPPING_URL),
        fetchText(CLASSEMENTS_CLUB_URL),
        fetchText(CALENDRIER_CLUB_URL),
      ]);
      const mappingRows = parseCSV(mapText).filter(r => (r['equipe_ffhb_proposee'] || '').trim() !== '');
      const classementsRows = parseCSV(clText);
      const calendrierRows = parseCSV(calText);
      return renderCalendriersClassementsPage(mappingRows, classementsRows, calendrierRows);
    }
"""


def generate_table_html(page: Page, site_url: str) -> str:
    page.goto(site_url)
    page.wait_for_load_state("networkidle")
    return page.evaluate(GENERATE_JS)


def split_intro_and_generated(current_html: str) -> tuple[str, str]:
    """Coupe le HTML actuel du champ en (intro à préserver, partie générée à remplacer) —
    même logique que push_planning_entrainements.py : le dernier <p> ouvrant avant le <table>
    marque la frontière."""
    table_idx = current_html.find("<table")
    if table_idx == -1:
        raise RuntimeError("Aucun <table> trouvé dans le contenu actuel de la page — structure inattendue, arrêt par prudence.")
    p_idx = current_html.rfind("<p", 0, table_idx)
    if p_idx == -1:
        raise RuntimeError("Aucun <p> trouvé avant le <table> — impossible de délimiter intro/généré, arrêt par prudence.")
    return current_html[:p_idx], current_html[p_idx:]


# Texte d'intro demandé par Julien (2026-08-20) : explique le périmètre de la page (seules les
# équipes avec un championnat actif y figurent) + renvoie vers la liste complète des équipes.
# INTRO_MARKER = sous-chaîne stable utilisée pour détecter si ce texte est déjà présent dans
# l'intro préservé — injecté une seule fois (idempotent, sûr à ré-exécuter à chaque run) plutôt
# que figé en dur côté page à la main, pour ne pas dépendre d'une étape manuelle oubliable.
INTRO_MARKER = "championnat actif"
EXTRA_INTRO_HTML = (
    '<p>Seules les équipes engagées dans un championnat actif sont listées ici. '
    "Retrouvez la liste complète des équipes du club dans le menu "
    '<a href="https://www.sportingvillette.com/saison-2026-2027/equipes" target="_blank" rel="noopener">Équipes</a>.</p>'
)


def push_calendriers_classements(page: Page, site_url: str = SITE_URL, *, dry_run: bool = False) -> dict:
    """Point d'entrée réutilisable : met à jour (ou juste prévisualise si dry_run) la page
    "Calendriers, résultats, classements" en utilisant une page Playwright déjà authentifiée.
    Ne gère PAS le lancement du navigateur ni la connexion — c'est la responsabilité de
    l'appelant (voir `main()` ci-dessous, ou push_sportsregions_fiches.py pour l'enchaînement)."""
    new_generated = generate_table_html(page, site_url)

    page.goto(admin_bridge(f"/page/edit/{PAGE_ID}"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    page.wait_for_selector("#ckeditor_contenu", state="attached")
    page.wait_for_function("window.CKEDITOR && window.CKEDITOR.instances['ckeditor_contenu']")
    page.wait_for_timeout(500)
    current = page.evaluate("window.CKEDITOR.instances['ckeditor_contenu'].getData()")

    intro, old_generated = split_intro_and_generated(current)
    if INTRO_MARKER not in intro:
        intro = intro + EXTRA_INTRO_HTML

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
    ap.add_argument("--dry-run", action="store_true", help="Génère et affiche (intro préservé + nouveau tableau), ne pousse rien (mais se connecte quand même en lecture seule pour prévisualiser l'intro actuel de la page)")
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

        result = push_calendriers_classements(page, args.site, dry_run=args.dry_run)

        if result["dry_run"]:
            print("===== INTRO PRÉSERVÉ (inchangé) =====")
            print(result["intro"])
            print("===== ANCIEN TABLEAU (sera remplacé) =====")
            print(result["old_generated"])
            print("===== NOUVEAU TABLEAU GÉNÉRÉ =====")
            print(result["new_generated"])
        else:
            print('>>> Page "Calendriers, résultats, classements" mise à jour.', file=sys.stderr)

        browser.close()


if __name__ == "__main__":
    main()
