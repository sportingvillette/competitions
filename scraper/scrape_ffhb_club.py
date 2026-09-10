# scrape_ffhb_club.py
# Scrape le calendrier/classement de toutes les equipes du club listees dans le Google Sheet.
#
# Usage interactif (local, comme avant) :
#   python scrape_ffhb_club.py
#
# Usage CI (non interactif, utilise par le workflow GitHub Actions) :
#   python scrape_ffhb_club.py sync-mapping --mapping-dir scraper
#   python scrape_ffhb_club.py scrape --mapping-dir scraper --outdir data [--teams id1,id2]
#
# team_mapping.csv est le rapprochement approximatif nom sheet <-> nom FFHB. Il est
# versionne dans le repo et NE DOIT PAS etre ecrase aveuglement a chaque run : une fois
# une ligne corrigee a la main (cas "club porteur" d'une entente, cf CLAUDE.md), elle doit
# etre preservee. sync-mapping n'ajoute que les lignes nouvelles (nouvelles equipes/phases
# apparues dans le sheet), sans toucher aux lignes existantes.
import argparse
import datetime
import json
import os
import re
import sys
import urllib.request
from difflib import SequenceMatcher

import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scrape_ffhb import (
    clean_text,
    slugify,
    parse_table_by_heading,
    scrape_poule_journees,
    normalize_poule_base_url,
    enrich_salle,
    sentence_case,
    strip_postal_code,
    strip_category_prefix,
    title_case_fr,
    save_if,
)

SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vT3RqA-z8ANNaXXsYMgh4ynk8LV4EjOnkAqyThzFQ4TcxIUofmVlWg20wyfw-ZmeDettPCjkCgank_3"
    "/pub?output=csv"
)

STOPWORDS = {"entente", "handball", "hb", "club", "association", "asc", "as", "sporting"}

def team_keywords(section: str) -> list:
    section = re.sub(r"\(.*?\)", " ", section)
    tokens = re.findall(r"[A-Za-zÀ-ÿ0-9]+", section.upper())
    return [t for t in tokens if t.lower() not in STOPWORDS and len(t) > 1]

def match_team_name(section: str, candidates: list):
    keywords = team_keywords(section)
    if not keywords or not candidates:
        return None, 0.0, []
    scored = []
    for cand in candidates:
        cand_up = cand.upper()
        # \b sur mot entier : "EST" ne doit pas matcher dans "OUEST"
        hits = sum(1 for k in keywords if re.search(rf"\b{re.escape(k)}\b", cand_up))
        coverage = hits / len(keywords)
        sim = SequenceMatcher(None, " ".join(keywords), cand_up).ratio()
        score = 0.7 * coverage + 0.3 * sim
        scored.append((cand, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    best_name, best_score = scored[0]
    return best_name, best_score, scored

def team_row_id(section: str, indice: str, categorie: str, phase: str) -> str:
    return slugify(f"{section}_{indice}_{categorie}_{phase}")

def clean_numeric_str(v) -> str:
    """clean_text(str(v)) mais retire le '.0' que pandas ajoute aux colonnes numériques
    contenant des valeurs manquantes (dtype float64), ex. '3.0' -> '3'."""
    s = clean_text(str(v or ""))
    return s[:-2] if re.match(r"^\d+\.0$", s) else s

def load_sheet_teams() -> pd.DataFrame:
    df = pd.read_csv(SHEET_CSV_URL, encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]
    rows = []
    for _, r in df.iterrows():
        section = clean_text(str(r.get("Section", "") or ""))
        if not section:
            continue
        indice = clean_text(str(r.get("Indice équipe", "") or "")) if pd.notna(r.get("Indice équipe")) else ""
        categorie = clean_text(str(r.get("Categorie", "") or ""))
        genre = clean_text(str(r.get("Genre", "") or ""))
        for phase, lien_col, niveau_col, poule_col in [
            ("P1", "P1.Lien", "P1.Niveau", "P1.Poule"),
            ("P2", "P2.Lien", "P2.Niveau", "P2.Poule"),
        ]:
            lien = str(r.get(lien_col, "") or "").strip()
            if not lien or lien.lower() == "nan" or not lien.startswith("http"):
                continue
            rows.append({
                "id": team_row_id(section, indice, categorie, phase),
                "section": section,
                "indice": indice,
                "categorie": categorie,
                "genre": genre,
                "phase": phase,
                "niveau": clean_text(str(r.get(niveau_col, "") or "")),
                "poule_num": clean_numeric_str(r.get(poule_col, "")),
                "lien": lien,
            })
    return pd.DataFrame(rows)

def get_poule_candidates(page, base_url: str) -> list:
    try:
        page.goto(base_url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_selector("table", timeout=20000)
    except Exception:
        pass
    soup = BeautifulSoup(page.content(), "lxml")
    classement = parse_table_by_heading(soup, ["Classement", "Classement général", "Tableau"])
    if classement is None or classement.empty:
        return []
    club_col = next(
        (c for c in classement.columns if "club" in str(c).lower() or "équipe" in str(c).lower()),
        classement.columns[1] if len(classement.columns) > 1 else classement.columns[0],
    )
    return [clean_text(str(v)) for v in classement[club_col].tolist()]

def resolve_new_teams(teams: pd.DataFrame) -> list:
    """Rapproche (fuzzy matching) chaque ligne de `teams` avec les équipes de sa poule."""
    if teams.empty:
        return []
    results = []
    candidates_by_poule = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for _, t in teams.iterrows():
            base_url = normalize_poule_base_url(t["lien"])
            if base_url not in candidates_by_poule:
                print(f"Lecture du classement -> {base_url}")
                candidates_by_poule[base_url] = get_poule_candidates(page, base_url)
            candidates = candidates_by_poule[base_url]

            best_name, best_score, scored = match_team_name(t["section"], candidates)
            top2_gap = (scored[0][1] - scored[1][1]) if len(scored) > 1 else 1.0
            a_verifier = (best_score < 0.5) or (top2_gap < 0.1)

            label = " ".join(x for x in [t["section"], t["indice"], t["categorie"], f"({t['phase']})"] if x)
            flag = " ⚠ A VERIFIER" if a_verifier else ""
            print(f"  {label} -> {best_name}  [confiance {best_score:.2f}]{flag}")

            results.append({
                "id": t["id"],
                "section": t["section"],
                "indice": t["indice"],
                "categorie": t["categorie"],
                "genre": t.get("genre", ""),
                "phase": t["phase"],
                "niveau": t["niveau"],
                "poule_num": t.get("poule_num", ""),
                "poule_url": base_url,
                "equipe_ffhb_proposee": best_name or "",
                "confiance": round(best_score, 2),
                "a_verifier": a_verifier,
                "candidats_poule": " | ".join(candidates),
            })
        browser.close()
    return results

def build_mapping(outdir: str):
    """Régénère team_mapping.csv en entier (usage local/manuel — écrase les corrections)."""
    teams = load_sheet_teams()
    print(f"{len(teams)} entrées équipe x phase avec lien trouvées dans le Google Sheet.\n")
    if teams.empty:
        print("Aucune équipe avec lien à traiter.")
        return

    results = resolve_new_teams(teams)
    mapping_df = pd.DataFrame(results)
    path = os.path.join(outdir, "team_mapping.csv")
    mapping_df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"\n✔ Mapping proposé -> {path}")
    n_verif = int(mapping_df["a_verifier"].sum())
    print(f"{n_verif} ligne(s) à vérifier manuellement (colonne 'a_verifier').")
    print("Corrigez au besoin la colonne 'equipe_ffhb_proposee' avant de lancer l'option 2.")

def sync_mapping(mapping_dir: str) -> int:
    """Ajoute au team_mapping.csv existant les lignes nouvelles du sheet, SANS toucher
    aux lignes déjà présentes (préserve les corrections manuelles). Retourne le nombre
    de lignes ajoutées."""
    mapping_path = os.path.join(mapping_dir, "team_mapping.csv")
    existing = pd.read_csv(mapping_path, encoding="utf-8-sig") if os.path.exists(mapping_path) else pd.DataFrame()
    existing_ids = set(existing["id"]) if not existing.empty and "id" in existing.columns else set()

    teams = load_sheet_teams()
    new_teams = teams[~teams["id"].isin(existing_ids)]
    print(f"{len(teams)} entrées équipe x phase dans le sheet, {len(new_teams)} nouvelle(s) à rapprocher.")

    new_rows = resolve_new_teams(new_teams)
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        updated = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
    else:
        updated = existing

    os.makedirs(mapping_dir, exist_ok=True)
    updated.to_csv(mapping_path, index=False, encoding="utf-8-sig")
    print(f"✔ team_mapping.csv à jour -> {mapping_path} ({len(new_rows)} ligne(s) ajoutée(s))")
    return len(new_rows)

def load_club_salle_cache(outdir: str) -> dict:
    path = os.path.join(outdir, "calendrier_club.csv")
    if not os.path.exists(path):
        return {}
    try:
        prev = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return {}
    cache = {}
    for _, row in prev.iterrows():
        score = str(row.get("score", "") or "").strip()
        gymnase = str(row.get("gymnase", "") or "").strip()
        lien = str(row.get("lien", "") or "").strip()
        if lien and score and gymnase:
            # Réapplique la mise en forme (sentence case + retrait code postal) sur les
            # valeurs relues du cache : les rattrape automatiquement au run suivant si elles
            # avaient été scrapées avant l'ajout de ce nettoyage, sans script de migration à part.
            gymnase = sentence_case(gymnase)
            ville = sentence_case(strip_postal_code(str(row.get("ville", "") or "")))
            cache[lien] = {
                "gymnase": gymnase,
                "ville": ville,
                "adresse_complete": str(row.get("adresse_complete", "") or ""),
            }
    return cache

FR_MONTHS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}
FR_MONTHS_FULL = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
                   "septembre", "octobre", "novembre", "décembre"]
FR_WEEKDAYS_FULL = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

MATCHS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQvskuueB25qKj0hbDWjFPomFdhfWRduUsNLp6Kv-za4t4oXcbbLsLrNsjwIt0ZH7C9B75pYBGDJfQu/"
    "pub?output=csv"
)

def format_confirmed_date(date_ddmmyyyy: str, heure_hhmm: str) -> str:
    """Inverse de parse_confirmed_date : (DD/MM/YYYY, HH:MM) -> "jour DD mois AAAA à HHhMM",
    même format que celui écrit par le scraper FFHB dans data/calendrier_club.csv."""
    d = datetime.datetime.strptime(date_ddmmyyyy.strip(), "%d/%m/%Y").date()
    h, m = heure_hhmm.strip().split(":")
    return f"{FR_WEEKDAYS_FULL[d.weekday()]} {d.day} {FR_MONTHS_FULL[d.month - 1]} {d.year} à {int(h):02d}H{m}"

def clean_val(v) -> str:
    """Convertit une valeur pandas en chaîne propre : "" pour NaN (piège fréquent — `v or ""`
    NE catche PAS NaN, qui est "truthy" en Python, d'où des "nan" littéraux constatés en test),
    sans le ".0" que pandas ajoute aux entiers d'une colonne à valeurs manquantes (dtype
    float64, ex. un score '28.0' au lieu de '28')."""
    if pd.isna(v):
        return ""
    s = str(v).strip()
    return s[:-2] if re.match(r"^\d+\.0$", s) else s

def sync_amicaux(mapping_dir: str, outdir: str) -> int:
    """Synchronise vers data/calendrier_club.csv les matchs marqués journée="Amical" saisis à
    la main par Julien dans la sheet "Matchs" — jamais scrapés depuis FFHB (ce ne sont pas des
    matchs officiels), donc jamais ajoutés autrement à ce fichier, qui alimente pourtant le post
    Instagram hebdo, la page "Calendrier & résultats" du site et la news hebdomadaire. Piège
    "club porteur" oblige (voir CLAUDE.md), la section d'un match n'est jamais déduite du nom de
    l'adversaire : jointure Catégorie/Genre/Index contre la sheet équipes (colonne Section),
    même logique que le filtre par périmètre de form-score-club-2-. `phase` retrouvée via
    team_mapping.csv si l'équipe y est déjà connue, vide sinon (non bloquant, cosmétique).

    UPSERT, pas juste "ajoute si absent" : la clé de recherche (indice, categorie,
    date/heure) exclut délibérément `section` — bug trouvé en conditions réelles (2026-09-04) :
    si la sheet équipes change entre 2 runs (ex. suffixe genre retiré de la colonne Section),
    une ligne déjà présente avec l'ANCIENNE section n'était plus reconnue et se faisait
    dupliquer plutôt que mise à jour. Ici, une correspondance trouvée met à jour TOUTE la ligne
    (section, phase, domicile, extérieur, score...) au lieu d'être ignorée — auto-corrige toute
    incohérence de section au run suivant plutôt que de la figer en doublon.

    domicile/extérieur nettoyés via _format_clean_opponent (même fonction que pour les vrais
    matchs FFHB scrapés, voir scrape_one_mapping_row) — sans ça, un nom "sale" tapé tel quel
    par Julien dans la sheet Matchs (ex. copié depuis Gesthand avec le préfixe de poule) reste
    sale indéfiniment, ce nettoyage n'ayant jamais lieu pour les lignes amicales autrement."""
    matchs = pd.read_csv(MATCHS_CSV_URL, encoding="utf-8")
    matchs.columns = [c.strip() for c in matchs.columns]
    amicaux = matchs[matchs["Journée"].fillna("").astype(str).str.strip().str.casefold() == "amical"]
    if amicaux.empty:
        print("Aucun match amical dans la sheet Matchs.")
        return 0

    equipes = pd.read_csv(SHEET_CSV_URL, encoding="utf-8")
    equipes.columns = [c.strip() for c in equipes.columns]
    section_index = {}
    for _, r in equipes.iterrows():
        key = (clean_val(r.get("Categorie")), clean_val(r.get("Genre")), clean_val(r.get("Indice équipe")))
        section = clean_val(r.get("Section"))
        if section:
            section_index[key] = section

    mapping_path = os.path.join(mapping_dir, "team_mapping.csv")
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig") if os.path.exists(mapping_path) else pd.DataFrame()
    phase_index = {}
    for _, r in mapping.iterrows():
        key = (clean_val(r.get("section")), clean_val(r.get("indice")), clean_val(r.get("categorie")))
        phase_index[key] = clean_val(r.get("phase"))

    cal_path = os.path.join(outdir, "calendrier_club.csv")
    existing = pd.read_csv(cal_path, encoding="utf-8-sig") if os.path.exists(cal_path) else pd.DataFrame()
    if not existing.empty:
        # dtype=str ne suffit pas à l'écriture : pandas déduit quand même un dtype par colonne
        # à la lecture (ex. "True"/"False" partout -> bool), qui refuse ensuite une
        # assignation .at[...] avec une chaîne (LossySetitemError). Toutes les colonnes
        # forcées en texte pour permettre n'importe quelle mise à jour cellule par cellule.
        existing = existing.astype(str).replace("nan", "")
    row_index_by_key = {}
    if not existing.empty:
        for idx, r in existing.iterrows():
            key = (clean_val(r.get("indice")), clean_val(r.get("categorie")), clean_val(r.get("date/heure")))
            row_index_by_key.setdefault(key, idx)  # 1re occurrence seulement, pas les doublons résiduels

    new_rows, updated_count, skipped = [], 0, []
    for _, r in amicaux.iterrows():
        code = clean_val(r.get("Code Gesthand"))
        categorie = clean_val(r.get("Catégorie"))
        genre = clean_val(r.get("Genre"))
        indice = clean_val(r.get("Index"))
        section = section_index.get((categorie, genre, indice), "")
        date_str = clean_val(r.get("Date"))
        heure_str = clean_val(r.get("Heure"))
        if not section or not date_str or not heure_str:
            skipped.append(code)
            continue
        try:
            date_heure = format_confirmed_date(date_str, heure_str)
        except ValueError:
            skipped.append(code)
            continue

        eq1s, eq2s = clean_val(r.get("Eq1Score")), clean_val(r.get("Eq2Score"))
        values = {
            "section": section, "indice": indice, "categorie": categorie,
            "phase": phase_index.get((section, indice, categorie), ""),
            "journée": "Amical", "date/heure": date_heure, "date_confirmee": "True",
            "domicile": _format_clean_opponent(clean_val(r.get("Eq1"))),
            "extérieur": _format_clean_opponent(clean_val(r.get("Eq2"))),
            "score": f"{eq1s} - {eq2s}" if eq1s and eq2s else "",
            "gymnase": clean_val(r.get("Gymnase")), "ville": clean_val(r.get("Ville")),
            "lien": "", "adresse_complete": "",
        }

        search_key = (indice, categorie, date_heure)
        row_idx = row_index_by_key.get(search_key)
        if row_idx is not None:
            changed = any(str(existing.at[row_idx, col]) != str(val) for col, val in values.items())
            if changed:
                for col, val in values.items():
                    existing.at[row_idx, col] = val
                updated_count += 1
        else:
            new_rows.append(values)
            row_index_by_key[search_key] = None  # évite un doublon si 2 lignes du Sheet partagent la même clé

    if skipped:
        print(f"  {len(skipped)} ligne(s) amicale(s) ignorée(s) (section ou date introuvable) : {skipped}")
    if not new_rows and not updated_count:
        print("Aucun amical à ajouter ou mettre à jour dans calendrier_club.csv.")
        return 0

    updated = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True) if new_rows else existing
    os.makedirs(outdir, exist_ok=True)
    updated.to_csv(cal_path, index=False, encoding="utf-8-sig")
    print(f"{len(new_rows)} match(s) amical(aux) ajoute(s), {updated_count} mis a jour dans calendrier_club.csv.")
    return len(new_rows) + updated_count

def parse_confirmed_date(date_str: str):
    """Retourne (DD/MM/YYYY, HH:MM) uniquement si la date est confirmée (format complet
    avec heure, ex. 'dimanche 13 septembre 2026 à 16H00'). Sinon (None, None) — on
    n'écrit jamais une date approximative dans la sheet Matchs."""
    if not date_str:
        return None, None
    m = re.search(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})\s+à\s+(\d{1,2})[hH](\d{2})", date_str)
    if not m:
        return None, None
    day, month_name, year, hour, minute = m.groups()
    month = FR_MONTHS.get(month_name.lower())
    if not month:
        return None, None
    return f"{int(day):02d}/{month:02d}/{year}", f"{int(hour):02d}:{minute}"

def extract_ffhb_id(lien: str) -> str:
    m = re.search(r"(rencontre-\d+)", lien or "")
    return m.group(1) if m else ""

def split_trailing_index(name: str):
    """Sépare un éventuel indice en suffixe du nom FFHB adverse, ex.
    'M18F EXC - ENTENTE LYON EST HANDBALL - 1' -> (base, '1'),
    'ST GENIS LAVAL AL HANDBALL 2' -> (base, '2'). Pas d'indice détecté -> ('', nom entier)."""
    name = (name or "").strip()
    m = re.match(r"^(.*\S)[\s-]+([A-Za-z]|\d{1,2})$", name)
    if m and len(m.group(1)) > 3:
        return m.group(1).strip(" -"), m.group(2)
    return name, ""

def _clean_opponent(raw: str):
    """Prépare le nom de l'équipe adverse pour la sheet : retire un éventuel
    préfixe de poule FFHB (ex. 'M16F EXC - '), isole un indice d'équipe en
    suffixe (split_trailing_index ci-dessus), puis met le nom de base en
    casse de titre (title_case_fr) plutôt que de garder la casse brute FFHB,
    souvent tout en majuscules."""
    stripped = strip_category_prefix((raw or "").strip())
    base, idx = split_trailing_index(stripped)
    return title_case_fr(base), idx

def _format_clean_opponent(raw: str) -> str:
    """Comme _clean_opponent, mais renvoie la chaîne assemblée ("Base - Idx" si un indice
    est détecté, sinon juste "Base") — même format que clean_opponent_label()/
    cleanOpponentLabel() côté affichage (build_weekend_payload.py / index.html). Utilisée
    pour nettoyer domicile/extérieur juste avant l'écriture dans calendrier_club.csv (voir
    scrape_one_mapping_row) : jusqu'ici seule la sheet Matchs recevait ce nettoyage (via
    _clean_opponent, dans build_match_payload), calendrier_club.csv gardait le nom FFHB brut
    (préfixe de poule + majuscules) — visible en clair par Julien, signalé le 2026-09-02."""
    base, idx = _clean_opponent(raw)
    return f"{base} - {idx}" if idx else base

def _s(v) -> str:
    """Convertit en chaîne en traitant NaN/None comme une chaîne vide (pandas transforme
    sinon un NaN en la chaîne littérale 'nan' via str())."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v).strip()

def build_match_payload(row, t) -> dict:
    """Construit le payload JSON pour un match scrapé, prêt à envoyer au Web App."""
    ffhb_id = extract_ffhb_id(_s(row.get("lien", "")))
    if not ffhb_id:
        return None

    domicile = _s(row.get("domicile", ""))
    exterieur = _s(row.get("extérieur", ""))
    us_name = _s(t.get("equipe_ffhb_proposee", ""))
    us_is_domicile = domicile.upper() == us_name.upper()

    our_indice = _s(t.get("indice", ""))
    if us_is_domicile:
        eq1, eq1x = t["section"], our_indice
        eq2, eq2x = _clean_opponent(exterieur)
    else:
        eq2, eq2x = t["section"], our_indice
        eq1, eq1x = _clean_opponent(domicile)

    date_ddmmyyyy, heure = parse_confirmed_date(_s(row.get("date/heure", "")))

    score = _s(row.get("score", ""))
    eq1score = eq2score = winlose = ""
    if " - " in score:
        s_dom, s_ext = [s.strip() for s in score.split(" - ", 1)]
        if s_dom.isdigit() and s_ext.isdigit():
            eq1score, eq2score = s_dom, s_ext
            us_score = int(s_dom) if us_is_domicile else int(s_ext)
            other_score = int(s_ext) if us_is_domicile else int(s_dom)
            winlose = "Victoire" if us_score > other_score else ("Défaite" if us_score < other_score else "Match Nul")

    return {
        "code": ffhb_id,
        "categorie": _s(t.get("categorie", "")),
        "genre": _s(t.get("genre", "")),
        "index": our_indice,
        "championnat": _s(t.get("niveau", "")),
        "poule": _s(t.get("poule_num", "")),
        "journee": _s(row.get("journée", "")),
        "eq1": eq1, "eq1x": eq1x,
        "eq2": eq2, "eq2x": eq2x,
        "date": date_ddmmyyyy or "",
        "heure": heure or "",
        "gymnase": _s(row.get("gymnase", "")),
        "ville": _s(row.get("ville", "")),
        "eq1score": eq1score,
        "eq2score": eq2score,
        "winlose": winlose,
    }

def post_match_to_sheet(payload: dict) -> bool:
    """Envoie un match au Web App Apps Script (upsert). No-op silencieux si
    SHEET_WEBAPP_URL / SHEET_WEBAPP_SECRET ne sont pas configurées (ex. en local)."""
    if not payload:
        return False
    url = os.environ.get("SHEET_WEBAPP_URL", "").strip()
    secret = os.environ.get("SHEET_WEBAPP_SECRET", "").strip()
    if not url or not secret:
        return False
    body = json.dumps({"secret": secret, "action": "add_match", "match": payload}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                print(f"    -> Sheet Matchs: {result.get('action')} ({payload['code']})")
                return True
            print(f"    -> Sheet Matchs ERREUR ({payload['code']}): {result.get('error')}")
            return False
    except Exception as e:
        print(f"    -> Sheet Matchs ERREUR réseau ({payload['code']}): {e}")
        return False

def sync_matches_to_sheet(team_calendrier, t) -> int:
    """Envoie chaque match de team_calendrier au Web App. Retourne le nombre de succès."""
    if team_calendrier is None or team_calendrier.empty:
        return 0
    n_ok = 0
    for _, row in team_calendrier.iterrows():
        payload = build_match_payload(row, t)
        if payload and post_match_to_sheet(payload):
            n_ok += 1
    return n_ok

_RUN_STARTED_AT = None

def post_progress(team_index=0, team_total=0, team_label="", phase=None,
                   journee=None, journee_total=None, match=None, match_total=None,
                   done=False, error=None):
    """Remonte une progression au Web App (best-effort — ne doit jamais faire échouer
    le scraping). Sans effet si SHEET_WEBAPP_URL/SECRET absentes ou hors d'un run CI.
    phase distingue les 2 étapes d'une équipe : "journees" (parcours des journées de
    la poule, toujours fait en entier) et "details" (gymnase/ville par match, qui saute
    les matchs déjà joués et connus — sans cette distinction la barre semblerait geler
    sur ces équipes-là)."""
    url = os.environ.get("SHEET_WEBAPP_URL", "").strip()
    secret = os.environ.get("SHEET_WEBAPP_SECRET", "").strip()
    if not url or not secret or not _RUN_STARTED_AT:
        return
    payload = {
        "secret": secret,
        "action": "progress",
        "progress": {
            "started_at": _RUN_STARTED_AT,
            "team_index": team_index,
            "team_total": team_total,
            "team_label": team_label,
            "phase": phase,
            "journee": journee,
            "journee_total": journee_total,
            "match": match,
            "match_total": match_total,
            "done": done,
            "error": error,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass

def scrape_one_mapping_row(page, poule_cache: dict, salle_cache: dict, t: dict, on_journee=None, on_match=None):
    """Scrape la poule d'une ligne de mapping (avec cache par poule) et retourne
    (lignes_calendrier_ou_None, ligne_classement_ou_None) pour cette équipe."""
    base_url = t["poule_url"]
    label = " ".join(str(x) for x in [t["section"], t["indice"], t["categorie"], f"({t['phase']})"] if str(x) and str(x) != "nan")
    print(f"\n=== {label} -> {t['equipe_ffhb_proposee']} ===\n{base_url}")

    if base_url not in poule_cache:
        calendrier, classement, _ = scrape_poule_journees(page, base_url, on_journee=on_journee)
        poule_cache[base_url] = (calendrier, classement)
    calendrier, classement = poule_cache[base_url]

    team_name = t["equipe_ffhb_proposee"]
    team_calendrier = None
    if calendrier is not None and not calendrier.empty:
        mask = (
            calendrier["domicile"].str.contains(team_name, case=False, na=False, regex=False)
            | calendrier["extérieur"].str.contains(team_name, case=False, na=False, regex=False)
        )
        team_df = calendrier[mask].reset_index(drop=True)
        if not team_df.empty:
            team_df = enrich_salle(page, team_df, salle_cache, on_match=on_match)
            team_df.insert(0, "phase", t["phase"])
            team_df.insert(0, "categorie", t["categorie"])
            team_df.insert(0, "indice", t["indice"])
            team_df.insert(0, "section", t["section"])
            n_synced = sync_matches_to_sheet(team_df, t)
            if n_synced:
                print(f"  ✔ {n_synced} match(s) synchronisé(s) vers la sheet Matchs.")
            # Nettoyage domicile/extérieur (préfixe de poule FFHB + casse) APRÈS la synchro
            # sheet, jamais avant : build_match_payload() compare domicile/extérieur BRUTS à
            # equipe_ffhb_proposee (égalité stricte) pour savoir quel côté est nous — nettoyer
            # plus tôt casserait cette comparaison pour CHAQUE match du club.
            team_df["domicile"] = team_df["domicile"].apply(_format_clean_opponent)
            team_df["extérieur"] = team_df["extérieur"].apply(_format_clean_opponent)
            team_calendrier = team_df
        else:
            print("  ⚠ Aucun match trouvé pour ce nom d'équipe dans la poule (mapping probablement faux).")

    team_classement = None
    if classement is not None and not classement.empty:
        cl = classement.copy()
        cl.insert(0, "phase", t["phase"])
        cl.insert(0, "categorie", t["categorie"])
        cl.insert(0, "indice", t["indice"])
        cl.insert(0, "section", t["section"])
        team_classement = cl

    return team_calendrier, team_classement

def run_club_scrape(outdir: str):
    """Scrape complet, usage local/interactif. Écrase entièrement les fichiers de sortie."""
    mapping_path = os.path.join(outdir, "team_mapping.csv")
    if not os.path.exists(mapping_path):
        print("⚠ Aucun team_mapping.csv trouvé. Lancez d'abord l'option 1 (génération du mapping).")
        return
    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["equipe_ffhb_proposee"] = mapping["equipe_ffhb_proposee"].fillna("").astype(str).str.strip()
    mapping["poule_url"] = mapping["poule_url"].fillna("").astype(str).str.strip()
    # poule_url != "" exclut les équipes sans championnat FFHB (ex. Loisirs, ajoutées à la
    # main dans team_mapping.csv juste pour le rapprochement domicile/extérieur des matchs
    # saisis manuellement — voir build_weekend_payload.py) : rien à scraper pour elles.
    mapping = mapping[(mapping["equipe_ffhb_proposee"] != "") & (mapping["poule_url"] != "")]
    if mapping.empty:
        print("⚠ Aucune équipe avec un nom FFHB validé dans team_mapping.csv.")
        return

    salle_cache = load_club_salle_cache(outdir)
    poule_cache = {}
    calendrier_rows = []
    classement_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for _, t in mapping.iterrows():
            cal, cls = scrape_one_mapping_row(page, poule_cache, salle_cache, t)
            if cal is not None:
                calendrier_rows.append(cal)
            if cls is not None:
                classement_rows.append(cls)
        browser.close()

    calendrier_club = pd.concat(calendrier_rows, ignore_index=True) if calendrier_rows else pd.DataFrame()
    classements_club = pd.concat(classement_rows, ignore_index=True) if classement_rows else pd.DataFrame()

    save_if(calendrier_club, os.path.join(outdir, "calendrier_club.csv"), "Calendrier club (toutes équipes)")
    save_if(classements_club, os.path.join(outdir, "classements_club.csv"), "Classements club (toutes équipes)")

def find_teams_without_match(full_mapping: pd.DataFrame, final_calendrier: pd.DataFrame, key_cols: list) -> list:
    """Sécurité demandée par Julien (2026-09-10, suite aux mappings cassés M18G B puis M18G D,
    tous deux invisibles en silence pendant des jours) : toute équipe de team_mapping.csv qui a
    un poule_url (donc un vrai championnat FFHB) DOIT avoir au moins 1 ligne dans
    calendrier_club.csv — si ce n'est pas le cas, c'est très probablement le même piège "club
    porteur" (equipe_ffhb_proposee qui ne correspond plus au nom affiché par la FFHB, cf
    CLAUDE.md), pas une absence légitime de match. Porte sur `full_mapping` (TOUTES les équipes
    mappées, pas seulement celles filtrées par --teams sur ce run précis) et sur
    `final_calendrier` (déjà fusionné avec les données des runs précédents) — sinon un run
    partiel masquerait une équipe cassée hors de son périmètre, ou un run qui vient de rescraper
    une équipe donnée verrait sa propre correction non reflétée avant fusion."""
    if full_mapping.empty:
        return []
    if final_calendrier is None or final_calendrier.empty:
        return list(full_mapping["id"])
    # fillna("") AVANT astype(str) des deux côtés — piège déjà documenté ailleurs dans ce
    # fichier (sync_amicaux) : `v or ""` ne catche PAS NaN (truthy en Python, donne le texte
    # littéral "nan"), et une colonne vide pour toutes les lignes d'un CSV (ex. "indice" pour
    # M16/M17, sans indice) est lue par pandas comme NaN, pas "". Première version de cette
    # fonction utilisait `t.get(c, "") or ""` ligne par ligne — retombait exactement dans ce
    # piège (indice="nan" côté mapping vs indice="" côté calendrier, aucune équipe sans indice
    # ne matchait jamais, 2 faux positifs constatés en testant : M16/M17).
    cal_keys = set(
        tuple(x) for x in final_calendrier[key_cols].fillna("").astype(str).itertuples(index=False, name=None)
    )
    mapping_keys = full_mapping[["id"] + key_cols].fillna("")
    for c in key_cols:
        mapping_keys[c] = mapping_keys[c].astype(str)
    missing = []
    for _, t in mapping_keys.iterrows():
        key = tuple(t[c] for c in key_cols)
        if key not in cal_keys:
            missing.append(t["id"])
    return missing


def _merge_by_key(prev: pd.DataFrame, new: pd.DataFrame, key_cols: list, preserve_col: str = None) -> pd.DataFrame:
    """Remplace dans `prev` les lignes des équipes présentes dans `new` (par key_cols),
    garde le reste de `prev` intact, ajoute les lignes de `new`.

    `preserve_col`, si fourni (ex. "journée"), protège de ce remplacement les lignes de
    `prev` dont cette colonne vaut "Amical" (insensible à la casse), même si leur clé
    d'équipe est aussi présente dans `new` — sinon un match amical/tournoi ajouté à la
    main (même équipe+phase que des matchs FFHB réels) se fait silencieusement effacer au
    prochain scraping de cette équipe (constaté le 2026-08-19 : 2 matchs du tournoi de
    Blavozy ajoutés le 2026-08-17 disparus après le cron nocturne suivant)."""
    if prev is None or prev.empty:
        return new
    if new is None or new.empty:
        return prev
    # fillna("") est indispensable : NaN != NaN en Python/pandas, donc sans ça les
    # équipes sans indice (ex. M16, M17 — colonne "indice" vide) ne se dédoublonnaient
    # jamais d'un run à l'autre, accumulant des lignes en double à chaque scraping.
    prev_keys = prev[key_cols].fillna("")
    new_keys = set(tuple(x) for x in new[key_cols].fillna("").itertuples(index=False, name=None))
    keep_mask = ~prev_keys.apply(lambda r: tuple(r) in new_keys, axis=1)
    if preserve_col and preserve_col in prev.columns:
        is_amical = prev[preserve_col].fillna("").astype(str).str.strip().str.casefold() == "amical"
        keep_mask = keep_mask | is_amical
    return pd.concat([prev[keep_mask], new], ignore_index=True)

def run_resync_sheet(mapping_dir: str, outdir: str, teams_filter: str):
    """Renvoie vers la sheet 'Matchs' (upsert add_match, par code FFHB) tous les
    matchs déjà présents dans data/calendrier_club.csv, SANS re-scraper FFHB —
    juste une relecture des CSV locaux + build_match_payload() + post. Sert à
    corriger rétroactivement des lignes déjà écrites dans la sheet après une
    évolution de build_match_payload() (ex. casse des noms d'adversaires,
    2026-08-17) : les futurs scrapes auraient la bonne casse de toute façon,
    ceci corrige l'historique déjà écrit sans attendre que chaque match soit
    re-scrapé naturellement. Idempotent (re-lancer plusieurs fois ne fait que
    ré-écraser les mêmes valeurs)."""
    mapping_path = os.path.join(mapping_dir, "team_mapping.csv")
    calendrier_path = os.path.join(outdir, "calendrier_club.csv")
    if not os.path.exists(mapping_path):
        print("⚠ Aucun team_mapping.csv trouvé.")
        sys.exit(1)
    if not os.path.exists(calendrier_path):
        print("⚠ Aucun calendrier_club.csv trouvé — rien à resynchroniser.")
        sys.exit(1)

    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["equipe_ffhb_proposee"] = mapping["equipe_ffhb_proposee"].fillna("").astype(str).str.strip()
    mapping = mapping[mapping["equipe_ffhb_proposee"] != ""]

    ids_filter = [s.strip() for s in teams_filter.split(",") if s.strip()] if teams_filter else []
    if ids_filter:
        mapping = mapping[mapping["id"].isin(ids_filter)]
    if mapping.empty:
        print("⚠ Aucune équipe à traiter (mapping vide ou filtre sans correspondance).")
        sys.exit(1)

    calendrier = pd.read_csv(calendrier_path, encoding="utf-8-sig")
    for col in ("section", "indice", "categorie", "phase"):
        calendrier[col] = calendrier[col].fillna("").astype(str)

    total_ok = 0
    for _, t in mapping.iterrows():
        t_indice = "" if pd.isna(t["indice"]) else str(t["indice"])
        mask = (
            (calendrier["section"] == str(t["section"]))
            & (calendrier["indice"] == t_indice)
            & (calendrier["categorie"] == str(t["categorie"]))
            & (calendrier["phase"] == str(t["phase"]))
        )
        team_calendrier = calendrier[mask]
        n_ok = sync_matches_to_sheet(team_calendrier, t)
        if n_ok:
            print(f"  ✔ {t['id']}: {n_ok} match(s) resynchronisé(s).")
        total_ok += n_ok
    print(f"Total : {total_ok} match(s) resynchronisé(s) vers la sheet Matchs.")

def run_club_scrape_ci(mapping_dir: str, outdir: str, teams_filter: str):
    """Scrape non interactif pour CI. Ne remplace que les équipes concernées dans les
    fichiers de sortie (les autres équipes gardent leurs données du run précédent) et
    écrit data/last_update.json avec le statut du run."""
    mapping_path = os.path.join(mapping_dir, "team_mapping.csv")
    if not os.path.exists(mapping_path):
        print("⚠ Aucun team_mapping.csv trouvé — lancez d'abord sync-mapping.")
        sys.exit(1)

    mapping = pd.read_csv(mapping_path, encoding="utf-8-sig")
    mapping["equipe_ffhb_proposee"] = mapping["equipe_ffhb_proposee"].fillna("").astype(str).str.strip()
    mapping["poule_url"] = mapping["poule_url"].fillna("").astype(str).str.strip()
    # poule_url != "" exclut les équipes sans championnat FFHB (ex. Loisirs, ajoutées à la
    # main dans team_mapping.csv juste pour le rapprochement domicile/extérieur des matchs
    # saisis manuellement — voir build_weekend_payload.py) : rien à scraper pour elles, sans
    # ce filtre le run nocturne échouerait dessus (URL vide) à chaque passage.
    mapping = mapping[(mapping["equipe_ffhb_proposee"] != "") & (mapping["poule_url"] != "")]
    # Copie AVANT le filtre --teams (qui suit) : sert à la vérification finale "toute équipe
    # avec un lien de poule doit avoir au moins 1 match dans calendrier_club.csv", qui doit
    # porter sur TOUTES les équipes mappées, même sur un run partiel qui n'en re-scrape que
    # certaines — sinon un run partiel masquerait les équipes cassées hors de son périmètre.
    full_mapping = mapping.copy()

    ids_filter = [s.strip() for s in teams_filter.split(",") if s.strip()] if teams_filter else []
    if ids_filter:
        mapping = mapping[mapping["id"].isin(ids_filter)]
    if mapping.empty:
        print("⚠ Aucune équipe à traiter (mapping vide ou filtre sans correspondance).")
        sys.exit(1)

    os.makedirs(outdir, exist_ok=True)
    calendrier_path = os.path.join(outdir, "calendrier_club.csv")
    classements_path = os.path.join(outdir, "classements_club.csv")
    prev_calendrier = pd.read_csv(calendrier_path, encoding="utf-8-sig") if os.path.exists(calendrier_path) else pd.DataFrame()
    prev_classements = pd.read_csv(classements_path, encoding="utf-8-sig") if os.path.exists(classements_path) else pd.DataFrame()

    salle_cache = load_club_salle_cache(outdir)
    poule_cache = {}
    calendrier_rows = []
    classement_rows = []
    refreshed_ids = []
    erreurs = []

    global _RUN_STARTED_AT
    _RUN_STARTED_AT = datetime.datetime.now(datetime.timezone.utc).isoformat()
    team_total = len(mapping)
    post_progress(0, team_total, "", done=False)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for team_index, (_, t) in enumerate(mapping.iterrows(), start=1):
            label = " ".join(str(x) for x in [t["section"], t["indice"], t["categorie"]] if str(x) and str(x) != "nan")

            def on_journee(j, num_journees, _idx=team_index, _label=label):
                post_progress(_idx, team_total, _label, phase="journees", journee=j, journee_total=num_journees)

            def on_match(m, num_matches, from_cache, _idx=team_index, _label=label):
                post_progress(_idx, team_total, _label, phase="details", match=m, match_total=num_matches)

            post_progress(team_index, team_total, label)
            try:
                cal, cls = scrape_one_mapping_row(page, poule_cache, salle_cache, t, on_journee=on_journee, on_match=on_match)
                if cal is not None:
                    calendrier_rows.append(cal)
                if cls is not None:
                    classement_rows.append(cls)
                refreshed_ids.append(t["id"])
            except Exception as e:
                print(f"  ❌ Erreur sur {t['id']}: {e}")
                erreurs.append(t["id"])
        browser.close()

    new_calendrier = pd.concat(calendrier_rows, ignore_index=True) if calendrier_rows else pd.DataFrame()
    new_classements = pd.concat(classement_rows, ignore_index=True) if classement_rows else pd.DataFrame()

    key_cols = ["section", "indice", "categorie", "phase"]
    final_calendrier = _merge_by_key(prev_calendrier, new_calendrier, key_cols, preserve_col="journée")
    final_classements = _merge_by_key(prev_classements, new_classements, key_cols)

    save_if(final_calendrier, calendrier_path, "Calendrier club")
    save_if(final_classements, classements_path, "Classements club")

    equipes_sans_match = find_teams_without_match(full_mapping, final_calendrier, key_cols)
    if equipes_sans_match:
        print(
            f"\n⚠ {len(equipes_sans_match)} équipe(s) avec un lien de poule FFHB mais 0 match "
            f"dans calendrier_club.csv (mapping probablement faux, cf CLAUDE.md 'club porteur') : "
            + ", ".join(equipes_sans_match)
        )

    status = {
        "derniere_maj": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": "partiel" if ids_filter else "complet",
        "equipes_rafraichies": refreshed_ids,
        "erreurs": erreurs,
        "equipes_sans_match": equipes_sans_match,
    }
    with open(os.path.join(outdir, "last_update.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(
        f"\n✔ last_update.json -> {len(refreshed_ids)} équipe(s) rafraîchie(s), {len(erreurs)} erreur(s), "
        f"{len(equipes_sans_match)} équipe(s) sans match malgré un lien FFHB."
    )
    all_problems = erreurs + equipes_sans_match
    post_progress(team_total, team_total, "", done=True, error=(", ".join(all_problems) if all_problems else None))
    if all_problems:
        # Fait échouer le run (notification GitHub Actions) même si equipes_sans_match est seul
        # en cause — une équipe avec lien FFHB et 0 match est presque toujours un mapping cassé
        # (cf find_teams_without_match), pas une absence légitime : mérite d'être vu tout de
        # suite plutôt que découvert par hasard des jours plus tard (vécu 2 fois, M18G B puis
        # M18G D).
        sys.exit(1)

def main():
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser(description="Scraper FFHB club (mode CI non interactif)")
        sub = parser.add_subparsers(dest="command", required=True)

        p_sync = sub.add_parser("sync-mapping", help="Ajoute les nouvelles équipes du sheet à team_mapping.csv")
        p_sync.add_argument("--mapping-dir", default="scraper")

        p_scrape = sub.add_parser("scrape", help="Scrape le calendrier/classement des équipes du mapping")
        p_scrape.add_argument("--mapping-dir", default="scraper")
        p_scrape.add_argument("--outdir", default="data")
        p_scrape.add_argument("--teams", default="", help="IDs séparés par des virgules (vide = toutes)")

        p_resync = sub.add_parser("resync-sheet", help="Renvoie les matchs déjà scrapés vers la sheet Matchs (upsert, sans re-scraper FFHB) — pour corriger rétroactivement des lignes déjà écrites")
        p_resync.add_argument("--mapping-dir", default="scraper")
        p_resync.add_argument("--outdir", default="data")
        p_resync.add_argument("--teams", default="", help="IDs séparés par des virgules (vide = toutes)")

        p_amicaux = sub.add_parser("sync-amicaux", help="Ajoute à calendrier_club.csv les matchs 'Amical' saisis à la main dans la sheet Matchs (jamais scrapés depuis FFHB)")
        p_amicaux.add_argument("--mapping-dir", default="scraper")
        p_amicaux.add_argument("--outdir", default="data")

        args = parser.parse_args()
        if args.command == "sync-mapping":
            sync_mapping(args.mapping_dir)
        elif args.command == "scrape":
            run_club_scrape_ci(args.mapping_dir, args.outdir, args.teams)
        elif args.command == "resync-sheet":
            run_resync_sheet(args.mapping_dir, args.outdir, args.teams)
        elif args.command == "sync-amicaux":
            sync_amicaux(args.mapping_dir, args.outdir)
        return

    print("Bonjour 👋 — Scraper FFHB club")
    print("1) Générer/mettre à jour le mapping équipes (team_mapping.csv)")
    print("2) Lancer le scraping complet du club (à partir du mapping validé)")
    try:
        choice = input("Choix (1/2) : ").strip()
    except EOFError:
        choice = ""

    outdir = os.path.join(os.path.dirname(__file__), "export")
    os.makedirs(outdir, exist_ok=True)

    if choice == "1":
        build_mapping(outdir)
    elif choice == "2":
        run_club_scrape(outdir)
    else:
        print("Choix invalide (1 ou 2 attendu).")

if __name__ == "__main__":
    main()
