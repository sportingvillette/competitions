#!/usr/bin/env python3
"""Construit le payload JSON des matchs à venir, regroupés par page du post
Instagram "planning des matchs" (Canva). Les matchs retenus sont ceux
tombant dans la fenêtre du mercredi au mardi suivant (centrée sur le
prochain week-end samedi/dimanche) — voir target_window() ; cette fenêtre
plus large que le seul week-end existe pour inclure les matchs Loisirs,
joués en semaine.

Source de données : `data/calendrier_club.csv` (un match par ligne) et
`scraper/team_mapping.csv` (identifie quel côté domicile/extérieur est
"nous"), lus en local par défaut ou via URL (--calendrier / --team-mapping
acceptent indifféremment un chemin local ou une URL http(s), ex. les URLs
GitHub Pages publiques du repo) pour un run sans accès au filesystem local
(ex. depuis une session planifiée type Cowork) :
    --calendrier https://sportingvillette.github.io/sv-planning-entrainements/data/calendrier_club.csv
    --team-mapping https://sportingvillette.github.io/sv-planning-entrainements/scraper/team_mapping.csv

Réutilise la même logique de nettoyage de nom d'adversaire et de parsing de
date que `index.html` (stripCategoryPrefix / splitTrailingIndex /
parseFrenchDate en JS) — voir CLAUDE.md section "Source de données" et
`cleanOpponentLabel` dans index.html. Toute modification de cette logique
doit être répercutée des deux côtés.

Usage :
    python scripts/build_weekend_payload.py \
        --calendrier data/calendrier_club.csv \
        --team-mapping scraper/team_mapping.csv \
        [--today 2026-08-11] [--out -]

Sortie (stdout par défaut) : JSON avec `weekend_label`, `saturday`,
`sunday`, `pages` (une clé par page du gabarit Canva, liste de lignes
{equipe, jour, recevant, visiteur, lieu}) et `domicile` (matchs à Villette
d'Anthon, toutes catégories, {equipe, jour, recevant, visiteur}). Une page
sans aucun match n'apparaît pas dans `pages` (le gabarit Canva ne doit pas
l'inclure cette semaine-là).
"""

import argparse
import csv
import io
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12,
}
MONTH_ABBR_FR = {
    1: "JAN", 2: "FÉV", 3: "MARS", 4: "AVR", 5: "MAI", 6: "JUIN",
    7: "JUIL", 8: "AOÛT", 9: "SEPT", 10: "OCT", 11: "NOV", 12: "DÉC",
}
WEEKDAY_ABBR_FR = {0: "Lun", 1: "Mar", 2: "Mer", 3: "Jeu", 4: "Ven", 5: "Sam", 6: "Dim"}  # Python weekday(): Monday=0..Sunday=6

# Sigles de club confirmés dans les données réelles — à garder tels quels
# plutôt que de les casser en 'Hbc'/'As'/'Us' (voir title_case_fr). Étendre
# si un nouveau sigle apparaît (heuristique best-effort, cf.
# scraper/scrape_ffhb.py où cette liste est dupliquée à l'identique).
KNOWN_ACRONYMS = {"HBC", "AS", "US", "CS", "ASUL", "UODL", "CSAV", "HB", "RC", "IDA"}
# Code de catégorie d'âge accolé au nom d'un club adverse (ex. "IDA U18F") — retiré, pas
# juste re-casé (pas plus légitime qu'un préfixe de poule standard). Dupliqué depuis
# scraper/scrape_ffhb.py, voir ce fichier pour le détail du pourquoi.
CATEGORY_CODE_RE = re.compile(r"^(\(?)([UM]\d{1,2}[FGM]?)(\)?)$", re.IGNORECASE)
FR_LOWER_WORDS = {"de", "du", "des", "et", "en"}
# 'la'/'le'/'les' volontairement exclus : trop souvent le début d'un nom
# propre composé dans les noms de club/lieu FFHB (ex. "Chambéry La Motte
# Servolex", "Le Havre") plutôt qu'un article grammatical — les mettre en
# minuscule casserait plus de cas réels que ça n'en corrigerait.
ELISION_RE = re.compile(r"^(d|l|n|j|m|t|s|c|qu)['’](\w.*)$", re.IGNORECASE)

# Regroupement des catégories en pages du gabarit Canva (ordre = ordre des
# pages 3 à 10 du design DAHSb3SEpJ4, vérifié directement via l'API Canva
# le 2026-08-26 : Seniors est en page 9, Loisirs en page 10 — donc APRÈS
# Seniors, pas avant). Catégories volontairement absentes (pas de
# championnat) : M5, Handfit. Loisirs joue en semaine (pas le week-end) —
# voir target_window() ci-dessous.
PAGE_ORDER = ["M7_M9", "M11", "M13", "M15", "M16_M17", "M18", "Seniors", "Loisirs"]
CATEGORIE_TO_PAGE = {
    "M7": "M7_M9", "M9": "M7_M9",
    "M11": "M11",
    "M13": "M13",
    "M15": "M15",
    "M16": "M16_M17", "M17": "M16_M17",
    "M18": "M18",
    "Loisirs": "Loisirs",
    "Seniors": "Seniors",
}
CATEGORIE_SORT_ORDER = {"M7": 0, "M9": 1, "M11": 2, "M13": 3, "M15": 4, "M16": 5, "M17": 6, "M18": 7, "Seniors": 8, "Loisirs": 9}
GENRE_SORT_ORDER = {"F": 0, "G": 1, "": 2}

DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})(?:\s+à\s+(\d{1,2})[hH](\d{2}))?")
STRIP_PREFIX_RE = re.compile(r"^[A-Za-zÀ-ÿ]*\d[A-Za-zÀ-ÿ0-9]*\s+[A-ZÀ-Ÿ0-9]+\s*-\s*(.+)$")
TRAILING_INDEX_RE = re.compile(r"^(.*\S)[\s-]+([A-Za-z]|\d{1,2})$")
GENRE_SUFFIX_RE = re.compile(r"\s*\([FG]\)\s*$")


def parse_french_dates(raw: str):
    """Toutes les dates trouvées dans une chaîne (1 pour une date confirmée,
    2 pour une plage "X au Y" non confirmée). Renvoie une liste de
    (date, heure_str_ou_None)."""
    if not raw:
        return []
    out = []
    for d, mo, y, h, mi in DATE_RE.findall(raw):
        month = MONTHS_FR.get(mo.lower())
        if month is None:
            continue
        out.append((date(int(y), month, int(d)), f"{int(h):02d}:{mi}" if h else None))
    return out


def strip_category_prefix(name: str) -> str:
    m = STRIP_PREFIX_RE.match(name)
    return m.group(1).strip() if m else name


def split_trailing_index(name: str):
    name = (name or "").strip()
    m = TRAILING_INDEX_RE.match(name)
    if m and len(m.group(1)) > 3:
        return m.group(1).rstrip(" -").strip(), m.group(2)
    return name, ""


def title_case_fr(name: str) -> str:
    """Casse de titre best-effort pour un nom de club FFHB (souvent tout en
    majuscules côté FFHB) : majuscule à chaque mot significatif, petits mots
    de liaison (de/du/des/la/le/les/et/en) en minuscules sauf en tout début
    de chaîne, article élidé (d'/l'/qu'...) en minuscules avec majuscule
    juste après l'apostrophe (ex. "L'ISERE" -> "l'Isere"), sigles connus
    (KNOWN_ACRONYMS) inchangés. Dupliqué depuis scraper/scrape_ffhb.py (ce
    fichier doit rester autonome/fetchable seul pour Cowork) — toute
    correction doit être répercutée dans les 2 endroits."""
    name = (name or "").strip()
    if not name:
        return name
    words = []
    for i, w in enumerate(name.split(" ")):
        if not w:
            words.append(w)
            continue
        core = re.sub(r"[^A-Za-zÀ-ÿ]", "", w)
        if core and core.upper() == core and core in KNOWN_ACRONYMS:
            words.append(w)
            continue
        if CATEGORY_CODE_RE.match(w):
            continue  # retiré, pas préservé — voir CATEGORY_CODE_RE ci-dessus
        lw = w.lower()
        if i > 0 and lw in FR_LOWER_WORDS:
            words.append(lw)
            continue
        elision = ELISION_RE.match(lw)
        if elision:
            words.append(f"{elision.group(1)}'{elision.group(2)[0].upper()}{elision.group(2)[1:]}")
            continue
        words.append(re.sub(r"(^|[-'’(])(\w)", lambda m: m.group(1) + m.group(2).upper(), lw))
    return " ".join(words)


def clean_opponent_label(raw: str) -> str:
    stripped = strip_category_prefix((raw or "").strip())
    base, idx = split_trailing_index(stripped)
    base = title_case_fr(base)
    return f"{base} - {idx}" if idx else base


def pretty_section(section: str) -> str:
    """Nom de club affichable : retire le suffixe genre '(F)'/'(G)' du nom
    de section (ex. 'Entente Lyon Est Handball (F)' -> 'Entente Lyon Est
    Handball')."""
    return GENRE_SUFFIX_RE.sub("", section or "").strip()


def next_saturday(today: date) -> date:
    """Samedi du prochain week-end à venir (si `today` est déjà samedi ou
    dimanche, renvoie le samedi de CE week-end)."""
    wd = today.weekday()  # Monday=0 .. Sunday=6
    if wd == 5:
        return today
    if wd == 6:
        return today - timedelta(days=1)
    return today + timedelta(days=(5 - wd))


def target_window(today: date):
    """Fenêtre de sélection des matchs : du mercredi au mardi suivant,
    centrée sur le prochain week-end (samedi/dimanche). Demande de Julien
    (2026-08-26) : la tâche édite le planning le mardi soir pour publication
    le mercredi, donc il faut annoncer "du mercredi au mardi suivant" pour
    inclure les matchs Loisirs (seule catégorie jouée en semaine, jamais le
    week-end) — sans conséquence pour les autres catégories, dont les matchs
    tombent de toute façon toujours dans cette fenêtre puisqu'elle englobe le
    week-end. Dérivée de next_saturday() (déjà éprouvée) plutôt que
    recalculée indépendamment, pour rester robuste quel que soit le jour
    exact où le script tourne."""
    saturday = next_saturday(today)
    sunday = saturday + timedelta(days=1)
    wednesday = saturday - timedelta(days=3)
    tuesday = saturday + timedelta(days=3)
    return wednesday, tuesday, saturday, sunday


def weekend_label(saturday: date, sunday: date) -> str:
    if saturday.month == sunday.month:
        return f"{saturday.day} & {sunday.day} {MONTH_ABBR_FR[saturday.month]}."
    return f"{saturday.day} {MONTH_ABBR_FR[saturday.month]}. & {sunday.day} {MONTH_ABBR_FR[sunday.month]}."


def equipe_label(categorie: str, genre: str, indice: str) -> str:
    """Pour les équipes Loisirs, `indice` vaut le genre lui-même (seul moyen
    de distinguer les 3 équipes Mixte/G/F dans team_mapping.csv, qui n'ont
    ni indice ni phase FFHB pour les différencier — voir team_mapping.csv).
    Sans le if ci-dessous, ça donnerait "Loisirs G G" au lieu de "Loisirs
    G"."""
    parts = [categorie]
    if genre:
        parts.append(genre)
    if indice and indice.casefold() != genre.casefold():
        parts.append(indice)
    return " ".join(parts)


def _read_csv(source: str) -> list:
    if source.startswith("http://") or source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=30) as resp:
            raw = resp.read().decode("utf-8-sig")
    else:
        with open(source, "r", encoding="utf-8-sig") as f:
            raw = f.read()
    return list(csv.DictReader(io.StringIO(raw)))


def load_team_mapping(source: str) -> dict:
    """Index (section, indice, categorie, phase) -> ligne team_mapping."""
    rows = _read_csv(source)
    index = {}
    for r in rows:
        key = (r.get("section", ""), r.get("indice", ""), r.get("categorie", ""), r.get("phase", ""))
        index[key] = r
    return index


def build_payload(calendrier_source: str, team_mapping_source: str, today: date) -> dict:
    calendrier_rows = _read_csv(calendrier_source)
    team_index = load_team_mapping(team_mapping_source)

    wednesday, tuesday, saturday, sunday = target_window(today)
    target_dates = {wednesday + timedelta(days=i) for i in range(7)}

    pages = {p: [] for p in PAGE_ORDER}
    domicile = []
    warnings = []
    included_team_keys = set()

    for row in calendrier_rows:
        section = row.get("section", "")
        indice = row.get("indice", "")
        categorie = row.get("categorie", "")
        phase = row.get("phase", "")
        if not section or categorie not in CATEGORIE_TO_PAGE:
            continue  # catégorie hors périmètre (M5/Handfit) ou ligne vide

        parsed = parse_french_dates(row.get("date/heure", ""))
        match_dates = [d for d, _ in parsed]
        if not any(d in target_dates for d in match_dates):
            continue  # pas dans la fenêtre mercredi -> mardi suivant

        confirmee = row.get("date_confirmee", "").strip().lower() == "true"
        match_date = next((d for d in match_dates if d in target_dates), None)
        heure = next((h for d, h in parsed if d == match_date and h), None) if confirmee else None

        if confirmee and match_date and heure:
            jour = f"{WEEKDAY_ABBR_FR.get(match_date.weekday(), '')} {heure}"
        else:
            jour = "Sam ou Dim"

        team = team_index.get((section, indice, categorie, phase))
        if team is None:
            warnings.append(f"Pas de team_mapping trouvé pour {section} / {indice} / {categorie} / {phase}")
            continue
        genre = team.get("genre", "")
        our_name = (team.get("equipe_ffhb_proposee", "") or "").strip()

        domicile_raw = (row.get("domicile", "") or "").strip()
        exterieur_raw = (row.get("extérieur", "") or "").strip()
        club_name = pretty_section(section)

        # "notre" côté matche soit le nom FFHB préfixé (our_name, ex. "M16F EXC - ENTENTE LYON
        # EST HANDBALL" — cas normal, matchs scrapés) soit le nom brut de la section (club_name,
        # ex. "Entente Lyon Est Handball") — un match ajouté à la main (amical, via
        # sync-amicaux/le formulaire du site) n'a jamais le préfixe FFHB, Julien tape le nom du
        # club tel quel. club_name est dérivé de LA MÊME ligne (row['section']), donc pas de
        # risque de faux positif entre 2 sections différentes. pretty_section() appliqué aussi
        # à domicile_raw/exterieur_raw pour la comparaison (pas pour l'affichage) : certaines
        # lignes amicales sont tapées avec le suffixe genre inclus ("Entente Lyon Est Handball
        # (F)"), que club_name a déjà retiré — sans ce nettoyage symétrique la comparaison
        # échouait encore (trouvé en testant le week-end du 5-6 septembre).
        # Depuis que scrape_ffhb_club.py nettoie domicile/extérieur avant écriture dans
        # calendrier_club.csv (title_case_fr + retrait préfixe FFHB — voir
        # _format_clean_opponent), domicile_raw/exterieur_raw ne sont PLUS au format brut FFHB
        # pour les matchs scrapés normaux : comparer our_name.casefold() == domicile_raw.casefold()
        # tel quel ne matche donc plus jamais. On compare our_name nettoyé par la MÊME pipeline
        # (clean_opponent_label, équivalent de _format_clean_opponent côté scraper) —
        # reconstruire "club_name - indice" ne marche pas car `indice` (colonne team_mapping,
        # ex. "A") n'a pas forcément le même format que le suffixe numérique/lettre du nom FFHB
        # (ex. "- 1") — trouvé en testant le week-end du 16-17 septembre (4 avertissements avant
        # ce correctif).
        our_name_clean = clean_opponent_label(our_name) if our_name else ""
        domicile_clean = pretty_section(domicile_raw)
        exterieur_clean = pretty_section(exterieur_raw)
        is_dom = (
            (our_name and our_name.casefold() == domicile_raw.casefold())
            or (our_name_clean and our_name_clean.casefold() == domicile_raw.casefold())
            or club_name.casefold() == domicile_clean.casefold()
        )
        is_ext = (
            (our_name and our_name.casefold() == exterieur_raw.casefold())
            or (our_name_clean and our_name_clean.casefold() == exterieur_raw.casefold())
            or club_name.casefold() == exterieur_clean.casefold()
        )

        if is_dom:
            recevant, visiteur, us_home = club_name, clean_opponent_label(exterieur_raw), True
        elif is_ext:
            recevant, visiteur, us_home = clean_opponent_label(domicile_raw), club_name, False
        else:
            warnings.append(
                f"Impossible de déterminer notre côté (dom={domicile_raw!r} ext={exterieur_raw!r} "
                f"attendu={our_name!r}) pour {section}/{indice}/{categorie} — ligne ignorée"
            )
            continue

        ville = (row.get("ville", "") or "").strip()
        lieu = ville if (confirmee and ville) else "Lieu à confirmer"

        entry = {
            "equipe": equipe_label(categorie, genre, indice),
            "jour": jour,
            "recevant": recevant,
            "visiteur": visiteur,
            "lieu": lieu,
            "journee": (row.get("journée", "") or "").strip(),
            "us_side": "recevant" if us_home else "visiteur",
            "_sort": (CATEGORIE_SORT_ORDER.get(categorie, 99), GENRE_SORT_ORDER.get(genre, 9), indice),
        }
        pages[CATEGORIE_TO_PAGE[categorie]].append(entry)
        included_team_keys.add((section, indice, categorie, phase))

        if confirmee and "villette d'anthon" in ville.casefold():
            domicile.append({k: entry[k] for k in ("equipe", "jour", "recevant", "visiteur", "us_side", "_sort")})

    for p in pages:
        pages[p].sort(key=lambda e: e["_sort"])
        for e in pages[p]:
            del e["_sort"]
    domicile.sort(key=lambda e: e["_sort"])
    for e in domicile:
        del e["_sort"]

    pages_non_vides = {p: rows for p, rows in pages.items() if rows}
    total_matches = sum(len(rows) for rows in pages_non_vides.values())
    stats = compute_context_stats(calendrier_rows, included_team_keys, saturday, sunday)
    stats["total_matches"] = total_matches

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weekend_label": weekend_label(saturday, sunday),
        "saturday": saturday.isoformat(),
        "sunday": sunday.isoformat(),
        "pages": pages_non_vides,
        "domicile": domicile,
        "stats": stats,
        "warnings": warnings,
    }


def compute_context_stats(calendrier_rows, included_team_keys, saturday: date, sunday: date) -> dict:
    """Quelques signaux dérivés du calendrier complet (pas juste ce week-end),
    utiles pour rédiger un sous-titre contextuel sur la page de couverture :
    nombre de matchs, s'agit-il du tout premier week-end avec un match dans
    tout le fichier, et — pour les équipes qui jouent ce week-end — le nombre
    de jours avant leur prochain match programmé (indice possible d'une
    trêve à venir si ce délai est nettement plus long qu'une semaine)."""
    # Les matchs amicaux/tournois (journee == "Amical", marqueur manuel -
    # voir les 2 matchs M16F du tournoi de Blavozy ajoutes le 2026-08-17)
    # sont exclus : un amical fin aout ne doit pas etre pris pour "le
    # premier week-end de la saison", ni fausser le delai avant le
    # prochain match officiel d'une equipe.
    all_dates = []
    by_team = {}
    for row in calendrier_rows:
        if (row.get("journée", "") or "").strip().casefold() == "amical":
            continue
        key = (row.get("section", ""), row.get("indice", ""), row.get("categorie", ""), row.get("phase", ""))
        dates = [d for d, _ in parse_french_dates(row.get("date/heure", ""))]
        all_dates.extend(dates)
        if key in included_team_keys:
            by_team.setdefault(key, []).extend(dates)

    # "min(all_dates) in (saturday, sunday)" et non "saturday <= min(...)" :
    # la 2e version serait vraie pour N'IMPORTE QUEL week-end avant le debut
    # de saison (ex. un week-end de juillet), pas seulement celui qui
    # contient vraiment le tout premier match - bug reel, pas juste un
    # probleme de matchs amicaux (trouve en testant le week-end du tournoi
    # de Blavozy, qui a revele que la condition etait deja trop large).
    season_opening_weekend = bool(all_dates) and min(all_dates) in (saturday, sunday)

    gaps_days = []
    teams_with_no_further_match = 0
    for key in included_team_keys:
        future_dates = [d for d in by_team.get(key, []) if d > sunday]
        if future_dates:
            gaps_days.append((min(future_dates) - sunday).days)
        else:
            teams_with_no_further_match += 1

    gaps_days.sort()
    median_gap_days = gaps_days[len(gaps_days) // 2] if gaps_days else None

    return {
        "teams_playing_this_weekend": len(included_team_keys),
        "season_opening_weekend": season_opening_weekend,
        "median_days_to_next_match": median_gap_days,
        "teams_with_no_further_match_scheduled": teams_with_no_further_match,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calendrier", default="data/calendrier_club.csv", help="Chemin ou URL du CSV calendrier")
    ap.add_argument("--team-mapping", default="scraper/team_mapping.csv", help="Chemin ou URL du CSV team_mapping")
    ap.add_argument("--today", help="Date de référence AAAA-MM-JJ (défaut : aujourd'hui) — pour tester un autre jour que le run réel")
    ap.add_argument("--out", default="-", help="Fichier de sortie JSON ('-' = stdout)")
    args = ap.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    payload = build_payload(args.calendrier, args.team_mapping, today)

    out_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out == "-":
        print(out_text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_text)

    if payload["warnings"]:
        print(f"\n{len(payload['warnings'])} avertissement(s) :", file=sys.stderr)
        for w in payload["warnings"]:
            print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
