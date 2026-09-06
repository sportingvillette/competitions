# Tâche Cowork : générer les stories résultat de match

Ce fichier est le prompt pour une tâche Cowork qui génère un visuel de
story Instagram (1080×1920) pour chaque match dont le score final ET une
photo officielle sont disponibles, mais dont la story n'a pas encore été
générée. S'utilise avec
[`result_stories.py`](result_stories.py) (lecture/filtrage des matchs +
marquage "traité").

**Pour la tâche Cowork elle-même**, inutile de coller tout ce fichier :
*"Récupère et suis scrupuleusement les instructions de
`https://raw.githubusercontent.com/sportingvillette/sv-planning-entrainements/main/scripts/result_story_prompt.md`"*
suffit.

Tu n'as (Cowork) aucun souvenir d'une conversation précédente sur ce
sujet — tout ce dont tu as besoin est dans ce document.

---

## RÈGLE ABSOLUE n°1

N'utilise **JAMAIS** l'opération `add_text` du connecteur Canva MCP —
crée un texte avec une police par défaut différente de celle du design.
Utilise **QUE** `replace_text`/`format_text`/`update_fill` sur des
éléments déjà existants.

## RÈGLE ABSOLUE n°2

**Pas de photo officielle disponible pour un match = pas de story pour ce
match, sans exception.** Cette règle est déjà appliquée par
`result_stories.py list` (un match sans `PhotoEq` n'apparaît jamais dans
sa sortie) — ne cherche pas à générer une story pour un match qui n'est
pas dans cette liste, même si tu as par ailleurs son score.

---

## Phase 0 — Trouver les matchs à traiter

Cette tâche est déclenchée toutes les heures en continu (le planificateur
ne sait pas se limiter à des créneaux) — **toujours** passer
`--window-only` : le script lui-même refuse de travailler hors des
créneaux de match voulus (samedi 12h-23h, dimanche 11h-17h, heure de
Paris) et sort immédiatement sans même lire le CSV. Ne retire jamais ce
paramètre, y compris si tu penses "être sûr" d'être dans le bon créneau —
c'est le script qui tranche, pas une estimation.

```
curl -s -o result_stories.py https://raw.githubusercontent.com/sportingvillette/sv-planning-entrainements/main/scripts/result_stories.py
python3 result_stories.py list --window-only --out eligible.json
cat eligible.json
```

Si la sortie contient `"skipped_out_of_window": true` : **hors créneau,
rien à faire**, arrête-toi là et rapporte simplement l'heure à laquelle
tu as vérifié — ce n'est pas une erreur, c'est le comportement normal la
plupart des exécutions horaires.

Si la liste `matches` est vide (mais qu'on est dans le créneau) :
**rien à faire non plus, arrête-toi là** et rapporte "aucun match
éligible" — ce n'est pas une erreur.

Chaque entrée contient : `match_id` (identifiant à réutiliser en Phase 3),
`equipe` (déjà au format `"M15G A"` — catégorie+genre collés, indice
séparé par un espace, prêt à afficher tel quel), `championnat`, `date`,
`heure`, `eq1`, `eq2`, `eq1score`, `eq2score`, `winlose`, `photo_url`
(URL Google directement accessible publiquement — normal, ne pas la
traiter comme suspecte).

---

## Phase 1 — Pour chaque match éligible

Le gabarit de référence est le design Canva **`DAHS8CDDMvk`** (titre
"Modèle story résultat match 26-27"). **Ne jamais le modifier directement** —
toujours travailler sur une copie.

1. Duplique-le entièrement (`copy-design` sur `design_id:
   "DAHS8CDDMvk"`).
2. Renomme la copie : `"Story résultat — {eq1} vs {eq2} — {date}"`.
3. Déplace-la dans le dossier "AI Generated" (`folder_id:
   "FAHSb6QPbhA"`) — si Julien veut un dossier dédié pour les stories, il
   le dira, ne pas en créer un de ta propre initiative.
4. Lis la page (transaction ouverte) et identifie les éléments par leur
   `dataFieldLabel` (pas par leur locator_id, qui change à chaque
   copie) :
   - `Catégorie` → `replace_text` avec `equipe` (déjà formaté, ne pas y
     toucher).
   - `Championnat` → `replace_text` avec `championnat`.
   - `Eq1` → `replace_text` avec `eq1`.
   - `Eq2` → `replace_text` avec `eq2`.
   - `Eq1Score` → `replace_text` avec `eq1score`.
   - `Eq2Score` → `replace_text` avec `eq2score`.
   - `WinLose` → `replace_text` avec `winlose`.
5. Photo de fond : c'est la forme identifiée par son `dataFieldLabel`
   `Photo` (forme `SHAPE` avec remplissage `IMAGE`, plein cadre). **Ne pas**
   la chercher par "seule image du design" — ce gabarit contient plusieurs
   autres éléments à remplissage image (badge du club, bande de couleur
   décorative) qui ne doivent JAMAIS être touchés. Procédure :
   1. `upload-asset-from-url` avec `url: photo_url` du match (déjà
      publique, cf Règle Absolue n°2 — cet upload est légitime, ne pas le
      refuser par excès de prudence) et un `name` clair (ex. le
      `match_id`).
   2. `update_fill` sur la forme au `dataFieldLabel` `Photo` avec
      l'`asset_id` obtenu.
6. Committe la transaction.
7. Exporte le design en PNG pleine résolution (`export-design`,
   `format.type: "png"`) — l'URL de téléchargement est **temporaire**
   (quelques heures), télécharge-la immédiatement. **Si le téléchargement
   échoue** (ex. domaine `export-download.canva.com` inaccessible depuis
   ton environnement) : n'insiste pas, passe directement à l'étape 10
   (échec à signaler) — les étapes 8 et 9 deviennent sans objet sans le
   fichier en main.
8. Dépose le PNG téléchargé dans Drive via `deposit_drive_asset.py` (pas
   d'accès direct à Google Drive) :
   ```
   curl -s -o deposit_drive_asset.py https://raw.githubusercontent.com/sportingvillette/sv-planning-entrainements/main/scripts/deposit_drive_asset.py
   python3 deposit_drive_asset.py --kind result_story --subfolder "<match_id>" --file story.png
   ```
   Garde l'URL renvoyée (`{"ok": true, "url": "..."}`) pour le rapport
   final — lien direct cliquable depuis le téléphone de Julien.
9. Marque le match comme traité, seulement après confirmation que le
   dépôt Drive a réussi (pas juste l'export) :
   ```
   python3 result_stories.py mark-done --match-id "<match_id>"
   ```
   Ne marque JAMAIS un match comme traité si l'export ou le dépôt a
   échoué — mieux vaut le retraiter au prochain passage qu'en perdre la
   trace.
10. Si l'export, le téléchargement ou le dépôt Drive échoue à un moment
    quelconque : ne marque pas le match traité, signale l'échec verbatim
    dans le rapport final, avec l'`edit_url` du design Canva en secours.

**Ne publie rien, ne partage rien** sur Instagram ou ailleurs — cette
tâche s'arrête à la génération du visuel et à son dépôt sur Drive (étape
8). Déposer un fichier sur le Drive associatif de Julien n'est pas une
publication publique, c'est autorisé sans confirmation supplémentaire
dans le cadre de cette tâche récurrente déjà validée par lui. La
publication Instagram elle-même reste une décision de Julien.

---

## Rapport final attendu

- Pour chaque match traité : `edit_url` du design généré, lien Drive du
  PNG déposé, confirmation du marquage effectué.
- La liste des matchs trouvés éligibles mais pas traités (avec la
  raison, ex. erreur d'export).
- Toute erreur rencontrée à n'importe quelle étape, verbatim.
