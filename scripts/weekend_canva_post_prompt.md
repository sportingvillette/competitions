# Tâche Cowork : générer le post Instagram "planning des matchs" du week-end

Ce fichier est le prompt complet à donner à une tâche planifiée Cowork
(hebdomadaire, mardi soir) pour générer automatiquement le post Instagram
"planning des matchs" du club de handball Sporting Villette. Il s'utilise
avec [`build_weekend_payload.py`](build_weekend_payload.py), qui fait le
travail de données (regroupement du calendrier par week-end et par page
du gabarit Canva).

**Pour la tâche Cowork elle-même**, inutile de coller tout ce fichier :
donne-lui simplement une instruction du type *"Récupère et suis
scrupuleusement les instructions de
`https://raw.githubusercontent.com/sportingvillette/sv-planning-entrainements/main/scripts/weekend_canva_post_prompt.md`"*.
Toute mise à jour de la procédure se fait alors en éditant ce fichier,
sans retoucher la configuration de la tâche planifiée.

Tu n'as (Cowork) aucun souvenir d'une conversation précédente sur ce
sujet — tout ce dont tu as besoin est dans ce document.

---

## RÈGLE ABSOLUE

N'utilise **JAMAIS** l'opération `add_text` du connecteur Canva MCP. Elle
crée un texte avec une police par défaut différente de celle du design
(déjà vérifié, source de bug corrigé manuellement une fois). Tu ne dois
utiliser **QUE** `replace_text` (changer le contenu d'un texte existant,
garde son formatage) et `delete_element` (supprimer un élément existant).
N'ajoute jamais un nouvel élément texte.

---

## Phase 0 — Récupérer les données du week-end

Exécute (Bash) :

```
curl -s -o build_weekend_payload.py https://raw.githubusercontent.com/sportingvillette/sv-planning-entrainements/main/scripts/build_weekend_payload.py
python3 build_weekend_payload.py \
  --calendrier https://sportingvillette.github.io/sv-planning-entrainements/data/calendrier_club.csv \
  --team-mapping https://sportingvillette.github.io/sv-planning-entrainements/scraper/team_mapping.csv \
  --out weekend_payload.json
cat weekend_payload.json
```

Si tu n'as pas accès à Bash/Python : arrête-toi et indique-le clairement
dans ton rapport final plutôt que d'essayer de reconstruire la logique à
la main (parsing de dates FR, nettoyage de noms d'adversaires) — c'est
fragile et non fiable si improvisé.

Le JSON contient :
- `weekend_label` (ex. `"17 & 18 JAN."`) — à écrire sur chaque page.
- `pages` : un objet avec au plus les clés `"M7_M9"`, `"M11"`, `"M13"`,
  `"M15"`, `"M16_M17"`, `"M18"`, `"Seniors"`, `"Loisirs"` — **seules les
  clés avec au moins un match sont présentes**. Chaque valeur est une liste
  de lignes
  `{equipe, jour, recevant, visiteur, lieu, journee, us_side}` (`journee`
  = numéro de journée FFHB, utile pour le contexte de la Phase 3, pas une
  colonne à afficher ; `us_side` = `"recevant"` ou `"visiteur"`, indique
  lequel des deux est notre club — utile en Phase 4 pour le souligner).
- `domicile` : liste de lignes `{equipe, jour, recevant, visiteur,
  us_side}` (matchs à domicile, toutes catégories, pour la page "à
  Villette").
- `stats` : signaux contextuels pour la Phase 3 (sous-titre de
  couverture) — voir cette phase pour le détail des champs.
- `warnings` : anomalies détectées par le script (mapping équipe
  introuvable, etc.) — à reporter, pas à ignorer.

---

## Phase 1 — Dupliquer le gabarit

Le gabarit de référence est le design Canva **`DAHSb3SEpJ4`** (titre
"Modèle post planning matchs 2026-27"), dans le dossier "AI templates".
**Ne jamais modifier ce design directement** — toujours travailler sur
une copie.

1. Duplique-le entièrement (`copy-design` sur `design_id: "DAHSb3SEpJ4"`)
   pour créer le post de cette semaine.
2. Vérifie que la copie a bien 10 pages (`page_count`). Si ce n'est pas le
   cas, arrête-toi et signale-le au lieu de continuer sur une base
   incomplète.
3. Renomme le design copié : `"Post planning matchs — {weekend_label}"`
   (ex. `"Post planning matchs — 17 & 18 JAN."`).
4. Déplace-le dans le dossier Canva "Post hebdo planning matchs"
   (`folder_id: "FAHSfQed5RE"`) via `move-item-to-folder` — c'est là que
   Julien va chercher les posts générés chaque semaine, ne saute pas
   cette étape. Si l'opération échoue quand même, ne bloque pas le reste
   de la tâche pour autant, mais signale-le bien en évidence dans ton
   rapport final (avec l'`edit_url`, pour qu'il retrouve le design même
   mal rangé).

Structure des 10 pages de ce design (fixe, toujours dans cet ordre) :

| Page | Contenu | Clé JSON |
|---|---|---|
| 1 | Couverture (pas de tableau) | — |
| 2 | "à Villette" / matchs à domicile — colonnes Équipe / Jour / Recevant / Visiteur (4 colonnes, **pas** de "Lieu du match") | `domicile` |
| 3 | M7 M9 | `M7_M9` |
| 4 | M11 | `M11` |
| 5 | M13 | `M13` |
| 6 | M15 | `M15` |
| 7 | M16 M17 | `M16_M17` |
| 8 | M18 | `M18` |
| 9 | Seniors | `Seniors` |
| 10 | Loisirs | `Loisirs` |

Pages 3 à 10 ont 5 colonnes : Équipe / Jour / Recevant / Visiteur / Lieu
du match. La page Loisirs (10) fonctionne exactement comme les autres pages
catégorie — seule différence : ses matchs (`jour` du JSON) tombent en
semaine plutôt que le week-end, c'est normal, ne pas s'en étonner ni le
"corriger".

---

## Phase 2 — Mettre à jour la date sur les 10 pages

Sur **chaque** page (1 à 10), il y a un texte de date au format
`"17 & 18 JAN."` (grande police ~120pt, distinct du titre de catégorie
et du texte "PLANNING DES MATCHS"). Remplace son contenu par
`weekend_label` du JSON (`replace_text`).

---

## Phase 3 — Rédiger le sous-titre de la page de couverture

La page 1 a un texte libre sous le titre "PLANNING DES MATCHS" (sous la
date, police normale, une phrase courte) que Julien personnalisait
manuellement chaque semaine. Rédige-le toi-même à partir de
`payload["stats"]` — une seule phrase courte en français, dans un
registre club/réseaux sociaux (voir exemple ci-dessous), pas une
description technique des chiffres.

Champs disponibles dans `stats` :
- `total_matches` : nombre de matchs ce week-end.
- `season_opening_weekend` (bool) : `true` si c'est le tout premier
  week-end de la saison avec un match programmé (aucun match plus tôt
  dans tout le calendrier).
- `median_days_to_next_match` : délai médian avant le prochain match des
  équipes qui jouent ce week-end. Une valeur nettement supérieure à 7-8
  jours (ex. 15+) suggère une trêve qui arrive juste après ce week-end.
- `teams_with_no_further_match_scheduled` : nombre d'équipes qui jouent
  ce week-end mais n'ont plus aucun match programmé après (fin de saison
  ou de phase pour elles, ou calendrier pas encore publié plus loin).

Choisis l'angle le plus pertinent (reprise de saison, trêve à venir,
gros week-end si beaucoup de matchs, sinon une phrase neutre du type
"Un week-end de matchs pour Sporting Villette"). Exemple de ton déjà
utilisé par Julien : *"Week end 100% à l'exterieur pour nos jeunes"*
(court, direct, pas de ponctuation lourde). Remplace le texte existant
de ce sous-titre par ta phrase (`replace_text`) — s'il n'existe pas de
texte libre distinct de la date/du titre sur cette page, n'invente pas
un nouvel élément (pas d'`add_text`) : indique-le dans ton rapport final
et passe à la suite sans bloquer.

---

## Phase 4 — Remplir chaque page catégorie (pages 3 à 10)

Pour chaque page dans l'ordre (3, 4, 5, 6, 7, 8, 9, 10), fais ce qui suit
dans une transaction dédiée (`read-design` avec `open_transaction: true`,
scope `filter.page_indices` sur cette seule page pour rester léger) :

1. Lis la page. Identifie : la forme rectangulaire d'en-tête (bleue, en
   haut du tableau — **ne pas y toucher**), puis les lignes de données
   suivantes = une forme rectangulaire (fond alterné clair/blanc) + les
   textes qui se superposent à elle, dans l'ordre visuel de haut en bas
   (trie par `top` croissant si besoin). Chaque ligne a 5 textes dans
   l'ordre des colonnes (Équipe, Jour, Recevant, Visiteur, Lieu du
   match), reconnaissables par leur position horizontale (`left`)
   croissante.

2. Récupère `json_rows = payload["pages"].get("<CLÉ_DE_CETTE_PAGE>", [])`.

   **Cas A — `json_rows` est vide** (page absente du JSON) : **ne
   supprime jamais la page** — la suppression de page Canva
   (`merge-designs`/`delete_pages`) exige qu'un humain tape littéralement
   la phrase *"I approve the deletion"*, ce qui est impossible à obtenir
   en session planifiée non surveillée (vérifié : c'est une règle codée
   en dur dans l'outil, pas une prudence de circonstance — ne retente pas
   `delete_pages` sur cette page). À la place, transforme le tableau de
   cette page en message "pas de match" :
   1. Garde la **première** ligne pré-construite (sa forme de fond + un
      seul de ses textes, par exemple celui de la colonne "Équipe") ;
      supprime les 4 (ou 3, page "à domicile") autres textes de cette
      même ligne (`delete_element`).
   2. Remplace le contenu du texte restant par `"Pas de match ce
      week-end"` (`replace_text`).
   3. Redimensionne-le pour qu'il occupe toute la largeur de la ligne
      (`left: 60, width: 960`) et recentre-le verticalement dans sa forme
      de fond avec la même formule qu'à l'étape 3 ci-dessous.
   4. Supprime entièrement toutes les autres lignes pré-construites de
      cette page (leur forme de fond ET leurs 5 textes chacune) via
      `delete_element` — c'est une suppression d'élément à l'intérieur
      d'une page, pas une suppression de page : aucune confirmation
      humaine n'est requise pour ça, c'est bien automatisable.

   **Cas B — `json_rows` a moins d'entrées que de lignes
   pré-construites sur la page** :
   - Pour les N premières lignes pré-construites (N = nombre d'entrées
     dans `json_rows`) : remplace le contenu des 5 textes par les
     valeurs correspondantes (`equipe`/`jour`/`recevant`/`visiteur`/
     `lieu`) via `replace_text`, dans l'ordre où tu as lu les lignes.
   - Pour les lignes pré-construites en trop (au-delà de N) : supprime-
     les entièrement (`delete_element` sur la forme de fond ET sur ses 5
     textes).

   **Cas C — `json_rows` a plus d'entrées que de lignes pré-construites
   disponibles** : ne force rien (pas d'`add_text`). Remplis les lignes
   disponibles, et note dans ton rapport final : *"page \<X\> : N
   match(s) non affiché(s), le gabarit n'a pas assez de lignes prévues —
   à agrandir manuellement."* Ce cas ne devrait normalement pas arriver
   (le gabarit a été dimensionné sur l'effectif réel de chaque
   catégorie) mais mieux vaut le signaler que le cacher.

3. Une fois les lignes conservées remplies (cas B ou C), pour **chaque**
   ligne conservée, dans l'ordre de haut en bas :
   1. Relis la hauteur réelle actuelle de chacun de ses 5 textes (elle
      vient de changer suite au `replace_text` — jamais la supposer,
      toujours la relire).
   2. Si la hauteur du texte le plus grand de la ligne dépasse la
      hauteur actuelle de la forme de fond de cette ligne : agrandis la
      forme de fond (`resize_element`) pour qu'elle fasse (hauteur du
      texte le plus grand + 20px de marge). Décale ensuite **toutes les
      lignes suivantes** de cette page (leur forme de fond ET leurs
      textes) vers le bas, du même delta (nouvelle_hauteur −
      ancienne_hauteur) — sinon elles se chevauchent.
   3. Recentre verticalement chacun des 5 textes de cette ligne dans sa
      forme de fond (dont la hauteur vient peut-être de changer à
      l'étape précédente) avec cette formule, appliquée individuellement
      à chaque texte :

      ```
      top_texte = top_forme + (hauteur_forme − hauteur_texte) / 2
      ```

      Utilise la hauteur réelle actuelle de chaque texte, pas une valeur
      supposée.
   4. Souligne le texte de notre club pour qu'il ressorte visuellement :
      `format_text` avec `formatting: {"decoration": "underline"}` sur le
      texte Recevant si `us_side == "recevant"`, ou sur le texte Visiteur
      si `us_side == "visiteur"` (jamais les deux, jamais l'autre côté).
      Testé et validé visuellement — fonctionne bien y compris sur un nom
      qui passe sur 2 lignes.

4. Committe la transaction de cette page avant de passer à la suivante.

---

## Phase 5 — Remplir la page 2 "à Villette" (matchs à domicile)

Même procédure que la Phase 4, mais avec `json_rows = payload["domicile"]`,
sur les lignes à 4 colonnes (Équipe/Jour/Recevant/Visiteur, pas de "Lieu
du match"). Si `domicile` est vide, applique le même traitement "Cas A"
(message "Pas de match ce week-end", page conservée).

---

## Phase 6 — Vérification finale

Relis le design entier (10 pages, aucune supprimée) pour un contrôle
visuel rapide : pas de chevauchement de texte visible, pages "pas de
match" lisibles et bien centrées, dates et sous-titre cohérents partout.

**Ne publie rien, ne partage rien, n'envoie rien** sur Instagram ou
ailleurs — cette tâche s'arrête à la génération du visuel et à son dépôt
sur Drive (Phase 7). Déposer un fichier sur le Drive personnel de Julien
n'est pas une publication publique, c'est autorisé sans confirmation
supplémentaire dans le cadre de cette tâche récurrente déjà validée par
lui.

---

## Phase 7 — Exporter en PNG et déposer sur Drive

1. Exporte chaque page du design en PNG (`export-design`, `format.type:
   "png"`, sans `pages` précisé pour exporter les 10 en une fois — vérifie
   d'abord `get-export-formats` sur ce design si tu as un doute).
2. Les URLs renvoyées sont **temporaires** (expirent en quelques heures) —
   télécharge chaque fichier immédiatement plutôt que de te contenter de
   garder les URLs de côté. **Si le téléchargement échoue** (ex. domaine
   `export-download.canva.com` inaccessible depuis ton environnement) :
   n'insiste pas, passe directement à l'étape 5 (échec à signaler), le
   reste de la Phase 7 devient sans objet sans les fichiers en main.
3. Une fois les 10 PNG en main localement, dépose-les un par un via le
   script `deposit_drive_asset.py` (pas d'accès direct à Google Drive) :

   ```
   curl -s -o deposit_drive_asset.py https://raw.githubusercontent.com/sportingvillette/sv-planning-entrainements/main/scripts/deposit_drive_asset.py
   python3 deposit_drive_asset.py --kind weekend_post --subfolder "<weekend_label>" --file 01-couverture.png
   python3 deposit_drive_asset.py --kind weekend_post --subfolder "<weekend_label>" --file 02-a-domicile.png
   ... (une fois par fichier)
   ```

   Nomme chaque fichier local de façon à ce que Julien s'y retrouve
   facilement depuis son téléphone, ex. `01-couverture.png`,
   `02-a-domicile.png`, `03-m7-m9.png`, `04-m11.png`, `05-m13.png`,
   `06-m15.png`, `07-m16-m17.png`, `08-m18.png`, `09-seniors.png`,
   `10-loisirs.png` (numérotées dans l'ordre des pages). `<weekend_label>`
   (ex. `"17 & 18 JAN."`) regroupe les 10 fichiers de ce run dans un même
   sous-dossier de "Temp posts Instagram" — n'invente pas d'autre
   emplacement, le script gère seul la création du sous-dossier.
4. Chaque appel réussi renvoie un JSON `{"ok": true, "url": "...",
   "fileId": "..."}` — garde ces 10 URLs pour le rapport final (lien direct
   cliquable depuis le téléphone de Julien, pas besoin qu'il navigue dans
   Drive).
5. Si l'export, le téléchargement ou le dépôt échoue à un moment
   quelconque, n'empêche pas le reste de la tâche d'avoir réussi —
   signale clairement l'échec dans ton rapport final (verbatim l'erreur),
   avec l'`edit_url` du design Canva en secours (Julien peut toujours
   exporter lui-même depuis l'appli Canva).

---

## Rapport final attendu

- Le `edit_url` du design généré.
- Le sous-titre rédigé en Phase 3 (texte exact utilisé).
- La liste des pages remplies avec de vrais matchs vs celles passées en
  "Pas de match ce week-end" (et pourquoi).
- Le contenu de `warnings` du JSON (Phase 0), s'il y en a.
- Tout cas C rencontré (page trop petite pour le nombre de matchs).
- Les 10 liens Drive renvoyés par `deposit_drive_asset.py` (ou l'échec
  rencontré, verbatim, avec l'edit_url Canva en secours).
- Toute erreur rencontrée à n'importe quelle étape, verbatim.

Le design final a toujours 10 pages (aucune page n'est jamais supprimée).
