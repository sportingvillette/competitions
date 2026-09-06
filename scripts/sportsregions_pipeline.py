"""Automatisation SportsRégions (site sportingvillette.com) via Playwright.

Identifiants lus depuis les variables d'environnement SPORTSREGIONS_USERNAME /
SPORTSREGIONS_PASSWORD (secrets GitHub Actions en CI — voir
.github/workflows/update-sportsregions.yml — ou exportées manuellement pour un
run local) — jamais en clair sur disque, jamais loggées ici.

L'admin SportsRégions vit sur un sous-domaine séparé (admin.sportsregions.fr)
avec sa propre session : on y accède via le pont SSO
`https://www.sportingvillette.com/login/go?l=<url encodée>` (sinon on retombe
sur un formulaire de connexion admin.sportsregions.fr distinct).

Usage :
    python sportsregions_pipeline.py --login-test         # connexion + sauvegarde session
    python sportsregions_pipeline.py --update-test <id>   # test d'écriture sur une équipe existante
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright, Page

SITE_URL = "https://www.sportingvillette.com"
ADMIN_URL = "https://admin.sportsregions.fr"
SESSION_FILE = Path(__file__).parent / "sportsregions_session.json"

SEL_OPEN_LOGIN = "#lien_user_lien"
SEL_IDENTIFIANT = "#login_identifiant"
SEL_PASSWORD = "#login_password"
SEL_SUBMIT = "a.bouton_connection"
SEL_2FA_CODE = "#code_2fa"

# Section CSV (competitions) -> valeur du <select> SportsRégions
# (vérifié dans #select_section_et_discipline_id, 2026-08-14)
SECTION_VALUES = {
    "Sporting Villette": "17255,0",
    "Entente Villette Genas": "17256,0",
    "Entente Lyon Est Handball": "17258,0",
    "Entente Est Lyonnais": "17257,0",
}
# Saison sportive -> valeur du <select> (vérifié 2026-08-14)
SAISON_VALUES = {
    "2025-2026": "26",
    "2026-2027": "27",
}


def get_credentials() -> tuple[str, str] | None:
    username = os.environ.get("SPORTSREGIONS_USERNAME")
    password = os.environ.get("SPORTSREGIONS_PASSWORD")
    if username and password:
        return username, password
    return None


def admin_bridge(path: str) -> str:
    """URL vers une page admin.sportsregions.fr, via le pont SSO obligatoire."""
    target = f"{ADMIN_URL}{path}"
    return f"{SITE_URL}/login/go?l={quote(target, safe='')}"


def login(page: Page, timeout_2fa_ms: int = 120_000) -> None:
    """Se connecte sur SportsRégions. Si une 2FA apparaît, laisse le temps à
    un humain de saisir le code dans la fenêtre visible avant de continuer
    (observé en pratique : passe seule sans intervention, y compris headless,
    depuis un réseau déjà connu du site — pas garanti depuis une IP inconnue
    comme celles de GitHub Actions, à vérifier à l'usage).
    """
    creds = get_credentials()
    if not creds:
        raise RuntimeError(
            "Identifiants SportsRégions absents : variables d'environnement "
            "SPORTSREGIONS_USERNAME / SPORTSREGIONS_PASSWORD non définies."
        )
    username, password = creds

    # page.goto + l'ouverture du formulaire ont chacun timeouté au moins une fois sur 4
    # tentatives depuis GitHub Actions le 2026-08-31 (page.goto puis page.click(SEL_OPEN_LOGIN),
    # séparément) — même famille de flakiness réseau transitoire que déjà documentée pour
    # push_sportsregions_fiches.py (net::ERR_TIMED_OUT en plein lot, 2026-08-18). 1 retry avant
    # d'abandonner, mais seulement sur cette étape AVANT tout remplissage de formulaire — jamais
    # retenter après avoir déjà rempli/soumis, pour ne pas risquer une double soumission ou
    # d'interférer avec une 2FA déjà déclenchée.
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            page.goto(SITE_URL)
            page.click(SEL_OPEN_LOGIN)
            last_error = None
            break
        except Exception as e:
            last_error = e
            if attempt == 0:
                print(f">>> Timeout/erreur au chargement de {SITE_URL} ({e}) — nouvelle tentative...")
                page.wait_for_timeout(3_000)
    if last_error is not None:
        raise last_error
    page.fill(SEL_IDENTIFIANT, username)
    page.fill(SEL_PASSWORD, password)
    page.click(SEL_SUBMIT)

    try:
        page.wait_for_selector(SEL_2FA_CODE, state="visible", timeout=5_000)
        print(">>> Code de double authentification demandé.")
        print(">>> Saisis-le toi-même dans la fenêtre du navigateur qui vient de s'ouvrir.")
        page.wait_for_selector(SEL_2FA_CODE, state="hidden", timeout=timeout_2fa_ms)
        print(">>> 2FA validée, poursuite.")
    except Exception:
        pass  # pas de 2FA déclenchée, ou déjà passée (session réutilisée)


def ensure_logged_in(page: Page) -> None:
    """Lève une erreur claire si la session a expiré (redirection vers le login
    admin) plutôt que de laisser le code appelant interpréter silencieusement
    une page de login comme une liste vide (faux négatifs en cascade)."""
    if "/login/" in page.url:
        raise RuntimeError(
            "Session SportsRégions expirée (redirigé vers une page de login). "
            "Relancer : python sportsregions_pipeline.py --login-test"
        )


def find_team_id(page: Page, nom: str) -> str | None:
    """Cherche une équipe par nom exact dans /groupe. Renvoie son id ou None."""
    page.goto(admin_bridge("/groupe"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    rows = page.eval_on_selector_all(
        "table tbody tr",
        """els => els.map(tr => {
            const link = tr.querySelector('a[href*="/groupe/edit/"]');
            const nameCell = tr.querySelector('td.titre, td.ellipsis');
            if (!link || !nameCell) return null;
            const m = link.href.match(/edit\\/(\\d+)/);
            return m ? { nom: nameCell.textContent.trim(), id: m[1] } : null;
        }).filter(Boolean)""",
    )
    for r in rows:
        if r["nom"] == nom:
            return r["id"]
    return None


def create_team(page: Page, nom: str) -> str:
    """Crée une équipe (juste le nom) via le popup 'Ajouter une équipe'. Renvoie son id."""
    page.goto(admin_bridge("/groupe"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    page.click("a.open_as_popup")
    page.wait_for_selector(".modal input[name=nom]", state="visible")
    page.fill(".modal input[name=nom]", nom)
    page.click(".modal button:has-text('Enregistrer')")
    page.wait_for_load_state("networkidle")

    # La liste met parfois un instant à refléter la création (constaté :
    # premier lookup en échec juste après un lot de créations) -> retry,
    # même pattern que la flakiness déjà documentée côté Apps Script.
    team_id = None
    for attempt in range(3):
        page.wait_for_timeout(1500)
        team_id = find_team_id(page, nom)
        if team_id:
            break
    if not team_id:
        raise RuntimeError(f"Équipe '{nom}' introuvable après création (3 tentatives).")
    return team_id


def update_team_content(
    page: Page,
    team_id: str,
    *,
    presentation_html: str,
    section_value: str,
    saison_value: str,
    chapo: str = "",
    invisible: bool = False,
    nom: str | None = None,
) -> None:
    """Remplit la fiche équipe (présentation, section, saison) et enregistre.

    `nom`, si fourni, renomme l'équipe (ex. correction de convention de nommage)."""
    page.goto(admin_bridge(f"/groupe/edit/{team_id}"))
    page.wait_for_load_state("networkidle")
    ensure_logged_in(page)
    # le textarea source de CKEditor reste caché (remplacé visuellement par
    # un iframe) : on attend juste sa présence dans le DOM, pas sa visibilité.
    page.wait_for_selector("#ckeditor_champ_libre", state="attached")
    page.wait_for_function("window.CKEDITOR && window.CKEDITOR.instances['ckeditor_champ_libre']")
    page.wait_for_timeout(500)  # laisse CKEditor finir son init

    if nom:
        page.fill("input[name=nom]", nom)
    if chapo:
        page.fill("#textarea_description", chapo)

    # CKEditor : on passe par son API JS plutôt que par le bouton "Source" de
    # l'UI (plus fiable, évite de dépendre de l'état d'affichage de l'iframe).
    page.evaluate(
        "([html]) => window.CKEDITOR.instances['ckeditor_champ_libre'].setData(html)",
        [presentation_html],
    )

    page.select_option("#select_section_et_discipline_id", value=section_value)
    page.select_option("#select_saison_id", value=saison_value)

    if invisible:
        page.check("#checkbox_invisible")
    else:
        page.uncheck("#checkbox_invisible")

    page.click("input.enregistrer")
    page.wait_for_load_state("networkidle")


def upload_illustration(page: Page, team_id: str, image_path: str) -> None:
    """Upload une image dans le champ 'Photo de l'équipe' (upload direct de
    fichier, pas d'URL) et enregistre."""
    page.goto(admin_bridge(f"/groupe/edit/{team_id}"))
    page.wait_for_selector("#file_upload_component_illustration", state="attached")
    ensure_logged_in(page)
    page.set_input_files("#file_upload_component_illustration", image_path)
    # l'upload se fait en AJAX dès la sélection du fichier ; le formulaire
    # affiche "Merci d'attendre la fin de l'envoi pour valider" -> on laisse
    # un peu de marge avant de cliquer Enregistrer.
    page.wait_for_timeout(4_000)
    page.click("input.enregistrer")
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except Exception:
        pass  # la sauvegarde a eu lieu ; seule cette attente de confort est flaky


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    with sync_playwright() as pw:
        headless = "--headed" not in args
        browser = pw.chromium.launch(headless=headless)
        # --login-test part TOUJOURS d'un contexte vierge (pas de storage_state existant) :
        # repartir d'une session (potentiellement expirée/cassée) fait planter le site sur
        # www.sportingvillette.com (le lien "Se connecter" #lien_user_lien ne s'affiche plus,
        # probablement un état ambigu ni vraiment connecté ni vraiment déconnecté côté site) —
        # constaté le 2026-08-18, 3 échecs consécutifs avec l'ancienne session réutilisée,
        # résolu instantanément avec un contexte neuf. Les autres commandes (--update-test)
        # continuent de réutiliser la session existante normalement.
        if args[0] == "--login-test":
            context = browser.new_context()
        else:
            context = (
                browser.new_context(storage_state=str(SESSION_FILE))
                if SESSION_FILE.exists()
                else browser.new_context()
            )
        page = context.new_page()

        if args[0] == "--login-test":
            login(page)
            page.wait_for_timeout(2_000)
            context.storage_state(path=str(SESSION_FILE))
            print(f">>> Session sauvegardée dans {SESSION_FILE}")
        elif args[0] == "--update-test" and len(args) > 1:
            team_id = args[1]
            html = "<p><i>Contenu de test envoyé par sportsregions_pipeline.py.</i></p>"
            update_team_content(
                page,
                team_id,
                presentation_html=html,
                section_value=SECTION_VALUES["Entente Est Lyonnais"],
                saison_value=SAISON_VALUES["2026-2027"],
            )
            print(f">>> Équipe {team_id} mise à jour.")
        else:
            print(__doc__)

        browser.close()


if __name__ == "__main__":
    main()
