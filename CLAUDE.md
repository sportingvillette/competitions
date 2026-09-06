# Contexte du projet — sv-planning-entrainements

Ce repo héberge des outils web pour **Sporting Villette** (club de handball,
Villette d'Anthon, Isère) et ses ententes partenaires. Tout est construit
comme une **application HTML statique unique** (`index.html`), sans backend,
hébergée sur **GitHub Pages**. Elle lit ses données en direct depuis un
Google Sheet publié en CSV, et génère plusieurs documents (plannings
d'entraînement, "Team Book") entièrement côté navigateur. Elle affiche aussi
le calendrier/résultats FFHB du club, scrapés côté CI (voir section dédiée
plus bas). Un **Web App Google Apps Script** (`apps-script/Code.gs`) sert de
seul point d'écriture vers la sheet "Matchs" partagée avec 2 autres repos
(saisie score/photo en direct pendant les matchs) — voir section dédiée.

Ce fichier est la **source de vérité pour transférer le contexte entre
sessions Claude Code** (le projet est repris régulièrement dans de nouvelles
conversations/contextes). À chaque nouvelle session : lire ce fichier en
entier avant de commencer, `git pull origin main` d'abord.

## Prochaine étape demandée par Julien (au moment de la rédaction)

**État (2026-08-15) : les 37 fiches équipe (contenu + illustration logo/nom)
sont générées et en ligne sur SportsRégions.** Session précédente très
productive sur ce chantier — détail complet, scripts et leçons apprises
dans la section dédiée **"Automatisation SportsRégions"** plus bas dans ce
fichier. Résumé :
- `renderEquipeFicheSportsRegions(r)` (dans `index.html`, sur la branche
  **`feature/fiche-equipe-sportsregions`, pas encore mergée ni pushée**)
  génère le bloc HTML "safe" (planning + entraîneurs + championnat) collé
  dans le champ CKEditor "Présentation" de chaque équipe SportsRégions.
- Script Python `sportsregions_pipeline.py` (dossier `97 - python`, **hors
  de ce repo**, à côté de `vpn_connect.py`/`shippingbo_pipeline.py`) pilote
  SportsRégions en Playwright : login+2FA, création/modification d'équipe,
  upload de l'illustration.
- Illustration = logo de section + nom d'équipe, générée via un connecteur
  Canva MCP (pas de script Python autonome pour cette partie — pilotée
  interactivement en session Claude Code, voir section dédiée pour la
  méthode et le piège à connaître).
- Convention de nommage des équipes SportsRégions :
  `{Catégorie}{Genre} {Indice}` (ex. `M11F A`, `M18G CF`, `SF A` pour
  Seniors) — genre **toujours** accolé à la catégorie, jamais de collision
  de nom entre sections.
- Prochaine sous-étape possible : import des matchs (calendrier) sur
  SportsRégions — piste identifiée (`admin.sportsregions.fr/evenement`,
  import CSV) mais **pas explorée**, limite connue : l'import n'ajoute
  jamais ne supprime.

## Hébergement

- Repo : `sportingvillette/sv-planning-entrainements` (public)
- GitHub Pages activé : Settings → Pages → branche `main` / `(root)`
- URL publique : `https://sportingvillette.github.io/sv-planning-entrainements/`
- **Important** : l'app fait des `fetch()` vers Google Sheets. Ces requêtes
  échouent si le fichier est ouvert en local (`file://...`) à cause de
  restrictions CORS/navigateur — il faut toujours tester via l'URL GitHub
  Pages ci-dessus (ou un serveur HTTP local, `python -m http.server`), jamais
  en double-cliquant sur le fichier téléchargé.

## Workflow de collaboration avec Julien

**Une branche par fonctionnalité, test local avant de pousser, PR ouverte,
et Julien donne un "ON MERGE" explicite avant toute fusion sur `main`** —
jamais de merge sans ce feu vert, même pour un correctif mineur. Une fois
mergé, supprimer la branche (locale + distante). Ce pattern s'applique aux
3 repos du projet (`sv-planning-entrainements`, `form-score-club-2-`,
`form-score-club-photo-only`).

`gh` (GitHub CLI) n'est pas installé dans l'environnement — utiliser `git`
directement (checkout branche, commit, push, puis merge local de `main` +
push une fois le "ON MERGE" reçu ; ouvrir la PR se fait juste en donnant le
lien `.../pull/new/<branche>` généré par le push, pas besoin de la créer
via API).

## Source de données

- Google Sheet équipes (édition) : `https://docs.google.com/spreadsheets/d/1viw-QLYXpA4jNV_bHhfCsBtJ8ueaC0ujXfqtPPpIAq0/edit?usp=sharing`
- Export CSV publié (utilisé par l'app, `Fichier > Partager > Publier sur le
  web > CSV`) :
  `https://docs.google.com/spreadsheets/d/e/2PACX-1vT3RqA-z8ANNaXXsYMgh4ynk8LV4EjOnkAqyThzFQ4TcxIUofmVlWg20wyfw-ZmeDettPCjkCgank_3/pub?output=csv`
- Onglet source : `Synthèse`
- Google Sheet "Com matchs réseaux" (matchs, onglet `Matchs`) : lue/écrite
  par le scraper + les formulaires club — voir section dédiée plus bas pour
  le détail des colonnes et du Web App qui l'écrit.
- **Piège connu, déjà rencontré plusieurs fois** : le CSV **publié** (les
  deux liens ci-dessus, et celui de la sheet Matchs) a un **délai de cache
  côté Google** après une écriture (observé de quelques secondes à ~15-20s,
  parfois plus) — une donnée qui vient d'être écrite via Apps Script peut ne
  pas apparaître immédiatement dans le CSV publié que lit le front. Ce n'est
  pas un bug de notre code : la sheet elle-même est à jour immédiatement,
  seul le CSV publié traîne. Ne pas chercher à "corriger" ça côté client
  au-delà d'un message d'attente/retry raisonnable.

### Colonnes du CSV équipes (une ligne = une équipe)

```
Section, Indice équipe, Categorie, Années de naissance, Prix_Licence, Genre,
E1.Lieu, E1.Jour, E1. Debut, E1.Fin,   (jusqu'à E4 — 4 créneaux d'entraînement max)
E2.Lieu, E2.Jour, E2. Debut, E2.Fin,
E3.Lieu, E3.Jour, E3. Debut, E3.Fin,
E4.Lieu, E4.Jour, E4. Debut, E4.Fin,
Entraineur1, Entraineur2, Entraineur3, Entraineur4,
P1.Niveau, P1.Lien, P1.Poule,   (Phase 1 de championnat — P1.Lien pointe vers une page de poule FFHB)
P2.Niveau, P2.Lien, P2.Poule,   (Phase 2, souvent vide en début de saison)
... (colonne AG) Description           (texte libre, saisi par Julien équipe par équipe — utilisé
                                        par la fiche SportsRégions ; lu par nom d'en-tête exact
                                        "Description" — pas "Description équipe" malgré le nom
                                        donné à la colonne dans le Sheet, ni par position)
```

- `Lieu` est au format `"Ville - Gymnase"` (ex. `"Genas - Halle des Sports"`),
  toujours séparé par ` - `.
- `Jour` est en français, une valeur parmi `Lundi..Samedi` (pas de dimanche
  actuellement dans la logique — si un jour Dimanche apparaît dans les
  données, il sera silencieusement ignoré par les vues planning : à corriger
  si besoin en étendant le tableau `DAYS`).
- `P1.Lien` / `P2.Lien` sont des URLs vers des pages de poule sur
  `ffhandball.fr`, base du scraper FFHB (voir plus bas).

### 4 ententes/sections (valeurs exactes de la colonne `Section`)

```
Sporting Villette
Entente Villette Genas
Entente Lyon Est Handball
Entente Est Lyonnais
```

Couleurs associées (utilisées comme code couleur dans les vues) :
```js
{
  'Sporting Villette': '#0b5e8f',
  'Entente Villette Genas': '#2f7d4f',
  'Entente Lyon Est Handball': '#a8452f',
  'Entente Est Lyonnais': '#8a5aab',
}
```

### Villes (code couleur additionnel utilisé dans les vues "par équipe")

```js
{
  "Villette d'Anthon": '#c0392b',
  'Meyzieu': '#5dade2',
  'Genas': '#1a3a6b',
  'Saint-Priest': '#d4ac0d',
  'Janneyrias': '#2e7d32',
  'Vaulx-En-Velin': '#e67e22',
  'Corbas': '#16a085',
}
```

## Architecture de `index.html`

Fichier unique, pas de build, pas de dépendance externe (pas de CDN, pas de
librairie JS tierce). Structure interne :

1. **UI** (thème sombre). Les panneaux d'action sont groupés par paires côte
   à côte (`.panel-row`, empilées sous 720px) : "Bases de données" +
   "Outils externes" (liens vers les 2 formulaires de saisie club et le repo
   GitHub), puis "Générer planning" + "Team Book".
2. **Logique de données** (fonctions `parseCSV`, `buildRecords`,
   `mergeRecords`, `finalLabel`) : parse le CSV en enregistrements par équipe,
   fusionne les lignes qui ont un horaire strictement identique (ex. deux
   équipes qui s'entraînent ensemble), calcule un libellé d'équipe.
3. **4 fonctions de rendu**, chacune retourne une chaîne HTML complète avec
   son propre `<style>` inline :
   - `renderEquipeComplet(merged)` — planning classique, jours en colonnes,
     équipes en lignes, avec légende et CSS en classes (usage : consultation
     libre / export).
   - `renderEquipeMinimal(merged)` — même contenu mais **sans classes CSS ni
     propriétés `display`/`padding`/`margin` en style inline** ; seulement
     `<br>`, `<b>`, `<i>` et `color`/`background-color`. Nécessaire car
     l'éditeur du site du club (SportsRégions) filtre agressivement le CSS
     collé — voir leçon ci-dessous.
   - `renderParGymnase(records)` — grille horaire (créneaux de 15 min) par
     gymnase, pour repérer les chevauchements. Amplitude horaire calculée
     dynamiquement par gymnase (pas de plage fixe). Fond jaune = chevauchement
     intégral (équipes regroupées, horaire identique) ; fond rouge = vrai
     conflit (chevauchement partiel, horaires différents).
   - `renderTeamBook(records, sectionName)` — génère une page de garde +
     une page par équipe (infos licence, entraînements, entraîneurs,
     niveau/poule championnat), format custom **100mm × 132mm** (calibré
     empiriquement pour tenir sur un "écran" de lecture mobile sans trop de
     vide, avec marge de sécurité pour le pire cas — 4 créneaux + 4
     entraîneurs + noms de gymnase longs qui retournent à la ligne).
4. **Génération PDF** : pas de librairie JS (voir leçon `html2pdf.js`
   ci-dessous). Utilise `window.print()` avec une règle CSS
   `@media print` qui masque tout sauf `#result-content`, plus une règle
   `@page` par vue pour forcer le bon format/orientation. L'utilisateur
   choisit "Enregistrer en PDF" dans la boîte de dialogue d'impression du
   navigateur.
5. **Vues calendrier/résultats FFHB** (`renderFFHBTable`, week-end par
   week-end, et `renderCalendrierCompletTable`, calendrier complet d'une
   équipe dans "Situation d'une équipe") — même présentation dans les deux
   vues : colonnes `Équipe` (uniquement dans la vue week-end) / `Classement`
   (`"3e vs 1er"`, rang domicile vs rang extérieur dans la poule, pas
   `"rang/nb équipes"`) / `Date` (`"samedi 19 ou dimanche 20 septembre"` si
   pas encore confirmée par FFHB, sinon la date exacte + heure) / `Dom/Ext`
   / `Adversaire` (nom nettoyé, cf `cleanOpponentLabel` : retire le préfixe
   type poule `"M16F EXC - "` et isole un indice d'équipe en suffixe type
   `"- 1"`) / `Score` / `Lieu`. Logique de classement/nettoyage partagée via
   `findPosInPoule`, `ordinalFr`, `cleanOpponentLabel`, `attachClassementLabels`.

## Leçons apprises (à ne pas refaire)

- **`file://` casse les `fetch()`** vers Google Sheets → toujours tester via
  l'URL GitHub Pages ou un serveur local, jamais en `file://`.
- **Google Drive n'exécute pas le HTML/JS** — un fichier `.html` déposé dans
  Drive ne fonctionne pas comme une page web, juste comme un fichier stocké.
- **`html2pdf.js` (rasterisation canvas) est peu fiable** : testé et
  abandonné — bug de pagination (doublait le nombre de pages à cause d'un
  mauvais calcul d'échelle canvas→PDF) et texte rendu en image (flou, non
  sélectionnable). Le rendu natif du navigateur (`window.print()` +
  `@media print` + `@page`) donne un résultat vectoriel fiable et est la
  méthode à privilégier pour tout futur export PDF (y compris pour un futur
  export PDF **automatisé côté CI** : Playwright sait aussi imprimer en PDF
  sans navigateur interactif, cf `page.pdf()` — piste pour le "résumé
  hebdomadaire" du roadmap plus bas, pas encore construit).
- **Éditeurs CMS tiers (SportsRégions) filtrent le CSS** collé dans leurs
  champs de texte enrichi : ils ne gardent souvent que `color` et
  `background-color`, suppriment `display`, `font-weight`, `padding`,
  `margin`, `border`. D'où l'existence de `renderEquipeMinimal`, qui
  n'utilise que des balises HTML structurelles (`<br>`, `<b>`, `<i>`) plutôt
  que du CSS pour la mise en forme.
- **`@page { size: ... }` en CSS n'est respecté par un outil d'impression
  automatisé que si on force l'option correspondante** (ex. Playwright
  nécessite `prefer_css_page_size: true`) — sinon le format par défaut
  (souvent Letter portrait) prend le dessus silencieusement.
- **La zone d'aperçu de l'app a `max-height` + `overflow:auto`** — override
  impératif en `@media print` (`max-height:none; overflow:visible;`) sinon
  l'impression tronque le contenu à la hauteur visible à l'écran.

### Leçons Google Apps Script (Web App `apps-script/Code.gs`)

- **`e.postData` n'est pas peuplé de façon fiable pour une requête
  multipart/form-data** envoyée par un vrai client externe (`fetch`/`FormData`,
  pas un formulaire HtmlService) — `e.postData.contents` peut être
  `undefined`, faisant planter un `JSON.parse` fait sans précaution. `doPost`
  ne doit tenter le parsing JSON que si `e.postData && e.postData.type ===
  'application/json'` explicitement ; tout le reste passe par `e.parameter`
  (champs de formulaire).
- **Un fichier envoyé en multipart/form-data externe n'arrive PAS en `Blob`
  dans `e.parameter`**, contrairement au comportement d'un `<input
  type=file>` dans un vrai formulaire HtmlService. Testé et confirmé en
  prod (action `debug_echo`, retirée depuis) : seuls les champs texte
  arrivent. La photo doit donc être encodée en **base64 côté client**
  (`photo_base64` + `photo_name` + `photo_type`) et redécodée côté serveur
  avec `Utilities.base64Decode` + `Utilities.newBlob`.
- **Ajouter un nouveau service (`DriveApp`, etc.) à un Web App déjà déployé
  nécessite une autorisation manuelle** : exécuter n'importe quelle fonction
  du projet une fois depuis l'éditeur Apps Script (bouton "Exécuter") pour
  déclencher l'écran de consentement, à valider avec le compte propriétaire
  de la sheet. Sans ça, le Web App déployé échoue silencieusement avec
  `"Vous n'êtes pas autorisé à appeler DriveApp..."`, même après un
  redéploiement. La lecture (`getFolderById`) et l'écriture
  (`createFolder`/`createFile`/`setSharing`) sont des **scopes distincts** :
  un test qui ne fait que lire ne garantit pas que l'écriture est autorisée.
- **"Nouvelle version" ≠ "Nouveau déploiement"** : après toute modification
  de `Code.gs` déjà en prod, utiliser Déployer > Gérer les déploiements >
  éditer (crayon) > **Nouvelle version** — jamais "Nouveau déploiement",
  qui changerait l'URL `/exec` et casserait tout ce qui la référence en dur
  (scraper, site, formulaires). Voir instructions détaillées en tête de
  `Code.gs`.
- **Le répertoire de travail local reflète la branche git extraite au
  moment où on regarde `apps-script/Code.gs`** — si une session Claude Code
  a laissé le repo sur `main` après avoir poussé une feature branche pas
  encore mergée, Julien qui recopie "le fichier du répertoire" pour le coller
  dans l'éditeur Apps Script récupère l'ancienne version sans le savoir, et
  un redéploiement ne change rien de visible. Piège déjà tombé dedans une
  fois. Réflexe : si un comportement censé être nouveau ne se manifeste pas
  après un redéploiement confirmé, vérifier `git branch --show-current` +
  `grep` d'une chaîne caractéristique du nouveau code dans le fichier avant
  de chercher ailleurs.
- **Le Web App répond parfois avec une latence/erreur transitoire** (redirection
  interne `script.googleusercontent.com` qui échoue ponctuellement, page
  d'erreur Google Drive générique "Impossible d'ouvrir le fichier", ou
  `secret invalide` alors que le secret est confirmé identique des deux
  côtés) — observé de façon répétée et aléatoire tout au long du
  développement, sur toutes les actions (`add_match`, `add_score`,
  `add_photo`, `list_photos`...), résolu à chaque fois par un simple retry
  quelques secondes après. Ce n'est pas un bug de code identifié : traiter
  comme une flakiness d'infrastructure Google à absorber par retry (2-3
  tentatives, ~1,5s d'écart) plutôt qu'à "corriger". Le front (`form-score-club-2-`)
  a maintenant ce retry intégré sur `list_photos`/`add_photo`/`select_photo`
  (voir section dédiée) — pattern à reprendre pour toute nouvelle action.
- **GitHub Actions retarde les `schedule:` programmés pile à l'heure ronde**
  (`:00`) — file d'attente saturée par tous les cron du même instant sur
  toute la plateforme, documenté par GitHub. Confirmé en prod : un cron à
  1h00 UTC pile a démarré avec ~2h30 de retard. Toujours décaler la minute
  (ex. `:13`) pour un cron sensible au timing.
- **Le cron GitHub Actions n'a pas de notion de fuseau horaire** (toujours
  UTC) — pour viser une heure locale française fixe toute l'année, il faut
  2 entrées `cron:` (une par saison CET/CEST), découpées par mois entier
  plutôt que par date exacte de changement d'heure (~1 semaine de décalage
  d'1h autour des 2 transitions annuelles, négligeable pour un cron de
  rafraîchissement de données). Voir `.github/workflows/scrape-ffhb.yml`.

## Scraper FFHB (calendrier / résultats / classements)

Pas de scraping côté navigateur (CORS + Playwright indisponible dans un
onglet) : scraping côté CI (GitHub Actions) qui commite des fichiers
statiques que `index.html` lit en `fetch()` same-origin, exactement comme il
lit déjà le Google Sheet. Écrit aussi directement dans la sheet "Matchs"
(voir section dédiée plus bas).

### Fichiers

- `scraper/scrape_ffhb.py` — briques de scraping réutilisables (Playwright +
  BeautifulSoup) : parcours des journées d'une poule FFHB, extraction
  calendrier/scores/classement, extraction gymnase/ville sur la page de
  détail d'un match (`extract_salle`, `sentence_case`, `strip_postal_code`,
  voir ci-dessous). Utilisable aussi en CLI interactif en local
  (`python scrape_ffhb.py`) indépendamment du club — mono-poule/mono-équipe.
- `scraper/scrape_ffhb_club.py` — orchestrateur multi-équipes club. Deux
  modes :
  - **Interactif local** (`python scrape_ffhb_club.py`, sans argument) :
    menu 1/2, comme avant.
  - **CLI non interactif** (utilisé par le workflow) :
    `sync-mapping --mapping-dir scraper` puis
    `scrape --mapping-dir scraper --outdir data --teams <ids ou vide>`.
- `scraper/team_mapping.csv` — **versionné**, rapprochement nom d'équipe du
  sheet (`Section`+`Indice équipe`+`Categorie`+phase) ↔ nom d'équipe affiché
  sur ffhandball.fr. Colonne `id` = clé stable (slug) utilisée pour cibler
  une équipe depuis l'UI ou le `workflow_dispatch`.
- `data/calendrier_club.csv`, `data/classements_club.csv` — sorties
  consolidées, une ligne par match/par classement avec colonnes
  `section/indice/categorie/phase` en tête. Lues par `index.html`.
- `data/last_update.json` — `{ derniere_maj, mode, equipes_rafraichies,
  erreurs }`, affiché dans l'UI.
- `.github/workflows/scrape-ffhb.yml` — cron (voir "Cron et fuseau horaire"
  ci-dessous) + `workflow_dispatch` (input `teams`, IDs séparés par
  virgules, vide = tout).

### Nettoyage Gymnase/Ville (sentence case + retrait code postal)

FFHB affiche ces deux champs tout en majuscules, avec le code postal en
préfixe pour la ville (ex. `"69740 GENAS"`, `"HALLE DES SPORTS"`). Deux
fonctions dans `scrape_ffhb.py` :
- `strip_postal_code(ville)` — retire un `"NNNNN "` en préfixe.
- `sentence_case(s)` — majuscule initiale seulement (reste en minuscules),
  y compris après un tiret ou une apostrophe (ex. `"VILLETTE D'ANTHON"` →
  `"Villette d'Anthon"`, `"SAINT-PRIEST"` → `"Saint-Priest"`) — heuristique
  best-effort sur les libellés observés, peut nécessiter un ajustement sur
  un cas non encore vu.

Appliqué à la fois à l'extraction fraîche (`extract_salle`) et à la
relecture du **cache** (`load_salle_cache` / `load_club_salle_cache`, qui
réutilisent gymnase/ville des matchs déjà joués sans re-scraper leur page
détail, cf ci-dessous) — les valeurs déjà scrapées avant l'ajout de ce
nettoyage se corrigent donc automatiquement au run suivant, sans script de
migration à part.

### Piège important : le "club porteur" d'une entente

Une entente de clubs (ex. `Entente Lyon Est Handball`) fait jouer chaque
équipe sous licence d'un seul club membre ("club porteur"), pas sous le nom
de l'entente. La ligue liste souvent ce club porteur (ex. `ST PRIEST
HANDBALL`, `AS LYON CALUIRE`) plutôt que le nom de l'entente sur
ffhandball.fr — le rapprochement automatique (fuzzy matching sur mots-clés)
échoue ou se trompe silencieusement sur ces cas, surtout en tout début de
saison. C'est pour ça que `team_mapping.csv` **n'est jamais régénéré en
entier automatiquement** : `sync-mapping` n'ajoute que les lignes vraiment
nouvelles (nouvelle équipe/phase apparue dans le sheet) et ne touche jamais
aux lignes déjà présentes, même si leur score de confiance était bas. Une
correction manuelle dans ce fichier (commit direct) est donc définitive tant
qu'elle n'est pas explicitement changée à la main.

### Fusion sélective (`--teams`)

Un run CI (manuel ou cron) ne réécrit dans `data/*.csv` que les lignes des
équipes effectivement rafraîchies ce run-là (`_merge_by_key` dans
`scrape_ffhb_club.py`, clé = `section+indice+categorie+phase`) — les autres
équipes gardent leurs données du run précédent. Indispensable pour que le
rafraîchissement manuel ciblé (cases à cocher dans l'UI) ne fasse pas
disparaître les données des équipes non sélectionnées.

### Cron et fuseau horaire

GitHub Actions n'évalue les triggers `schedule:` que sur la **branche par
défaut** (`main`) — le cron ne tournera qu'une fois ce workflow mergé, pas
sur une branche de feature.

Cron quotidien (couvre le week-end : matchs du dimanche scrapés dans la nuit
de dimanche à lundi), visant ~1h13 heure de Paris toute l'année via **2
entrées `cron:` saisonnières** dans le workflow (GitHub Actions n'a pas de
notion de fuseau horaire) :
- `13 0 * 11,12,1,2,3 *` (nov-mars, 0h13 UTC = ~1h13 CET)
- `13 23 * 4,5,6,7,8,9,10 *` (avr-oct, 23h13 UTC = ~1h13 CEST)

Découpage par mois entier plutôt que par date exacte de changement d'heure
(~1 semaine de décalage d'1h autour des 2 transitions annuelles, négligeable
ici). Minute décalée à `:13` (pas `:00`) pour éviter la contention de la
file d'attente GitHub au pile-hh:00 — voir leçon dédiée plus haut.

### Rafraîchissement manuel depuis l'UI

Le site restant 100% statique, le bouton "Lancer un rafraîchissement" appelle
directement l'API GitHub (`POST
/repos/{repo}/actions/workflows/scrape-ffhb.yml/dispatches`) depuis le
navigateur, avec un jeton **fine-grained PAT stocké en `localStorage`**
(jamais commité, jamais envoyé ailleurs qu'à `api.github.com`). Chaque
admin doit créer son propre jeton une fois par appareil (scope minimal :
`Actions: Read and write` sur ce repo uniquement).

### Barre de progression du rafraîchissement (équipe par équipe)

L'API GitHub Actions ne donne pas de vrai pourcentage, et streamer les logs
d'un job en cours n'est pas fiable. On utilise donc le Web App Apps Script
comme relais : `scrape_ffhb_club.py` (`post_progress`) pousse à chaque étape
un petit JSON dans `CacheService` (action `progress` de `Code.gs` — pas le
Sheet, purement éphémère, 6h de TTL). Le site sonde ça via
`doGet(?action=progress)` toutes les 3s (`PROGRESS_WEBAPP_URL`, hardcodée
dans `index.html` — l'URL n'est pas sensible en elle-même, seules les
actions d'écriture sont protégées par le secret partagé).

Chaque équipe a **2 phases séquentielles**, chacune pesant pour moitié du
créneau de l'équipe dans la barre :
- `phase: "journees"` (callback `on_journee` de `scrape_poule_journees`) —
  parcours intégral des journées de la poule, toujours fait en entier
  (impossible de savoir sans les visiter si un score est apparu).
- `phase: "details"` (callback `on_match` de `enrich_salle`) —
  gymnase/ville par match, qui **saute** les matchs déjà joués et connus
  (cache). Sans cette 2e phase distincte, la barre semblerait geler sur les
  équipes ayant beaucoup de nouveaux matchs à détailler, puisque la phase
  "journees" seule atteint 100% de son propre décompte bien avant que
  l'équipe entière soit terminée.

Un `started_at` (posé une fois par run) est comparé côté client au moment
du déclenchement pour ignorer une progression laissée par un run précédent
(sinon un `done:true` périmé stopperait le sondage immédiatement). Filet de
sécurité : arrêt du sondage après 90 min (un run peut prendre longtemps en
tout début de saison, sur les poules avec beaucoup de journées à parcourir).

## Web App Apps Script (`apps-script/Code.gs`) — point d'écriture unique

Un seul Web App lié à la sheet "Com matchs réseaux" (onglet `Matchs`),
partagé par le scraper (ce repo) et les formulaires club
(`form-score-club-2-`). **Doit être collé à la main dans l'éditeur Apps
Script de la sheet et déployé par Julien** (Claude Code n'a pas d'accès à
son compte Google) — instructions détaillées en tête de `Code.gs`, y compris
l'étape d'autorisation Drive (voir leçons ci-dessus).

Deux secrets distincts (défense en profondeur — si le JS public du
formulaire fuite, ça ne compromet pas le secret du scraper) :
- `SHARED_SECRET` — scraper uniquement (GitHub Actions, jamais exposé
  publiquement). Utilisé pour les requêtes **JSON** (`doPost` route vers ce
  chemin uniquement si `e.postData.type === 'application/json'`).
- `FORM_SHARED_SECRET` — formulaires club (JS public). Utilisé pour toutes
  les requêtes **multipart/form-data** (`e.parameter`).

### Actions disponibles

| Action | Méthode | Secret | Description |
|---|---|---|---|
| `add_match` | POST JSON | `SHARED_SECRET` | Upsert d'un match par le scraper (voir mapping des colonnes ci-dessous). |
| `progress` | POST JSON | `SHARED_SECRET` | Pousse la progression du scraping en cache éphémère (voir barre de progression). |
| `progress` | GET | aucun | Lit la progression (donnée non sensible). |
| `progress_sportsregions` | POST JSON | `SHARED_SECRET` | Même mécanique que `progress`, clé de cache distincte (`PROGRESS_CACHE_KEY_SPORTSREGIONS`) — suivi de `scripts/push_sportsregions_fiches.py` (workflow GitHub Actions "Mise à jour SportsRégions"), voir barre de progression dédiée sur le site. |
| `progress_sportsregions` | GET | aucun | Lit cette progression (donnée non sensible). |
| `add_score` | POST multipart | `FORM_SHARED_SECRET` | Écrit `Eq1Score`/`Eq2Score`/`WinLose` (sauf si verrouillé, cf `Score Source`) et/ou `Commentaire` (jamais verrouillé) — champs `score_dom`/`score_ext`/`winlose` **omis par le client** si le score est verrouillé, pour n'envoyer que le commentaire. |
| `add_photo` | POST multipart | `FORM_SHARED_SECRET` | Upload une photo (base64, voir leçon dédiée) dans le dossier Drive du match — **n'écrit plus `PhotoEq`** (alimente juste la galerie). |
| `select_photo` | POST multipart | `FORM_SHARED_SECRET` | Marque une photo déjà uploadée comme *la* photo officielle (écrit `PhotoEq`) — sélection manuelle uniquement, jamais automatique. |
| `list_photos` | GET | aucun | Liste toutes les photos du dossier Drive d'un match (donnée non sensible, déjà partagée "anyone with link"). |
| `mark_story_done` | POST multipart | `FORM_SHARED_SECRET` | Écrit `Story résultat` (horodatage ISO par défaut, ou `p.value` si fourni) — marque qu'une story résultat a été générée pour ce match, pour que la génération automatique ne le retraite pas. Colonne réutilisée avec l'accord de Julien (voir note `Story*` ci-dessous). |
| `add_asset` | POST multipart | `FORM_SHARED_SECRET` | Dépose un fichier (PNG base64) dans un sous-dossier de `WEEKEND_POSTS_FOLDER_ID` (`kind: "weekend_post"`) ou `RESULT_STORIES_FOLDER_ID` (`kind: "result_story"`) — mêmes dossiers Drive que "Photos matchs" mais dédiés aux visuels Canva générés par Cowork (voir `scripts/deposit_drive_asset.py`), sous-dossier = `p.subfolder` (weekend_label ou match_id). Contourne le besoin d'un accès Drive direct depuis Cowork — reste un point de défaillance externe à ce mécanisme : le téléchargement du PNG exporté depuis Canva (`export-download.canva.com`), qui a déjà été observé bloqué au niveau réseau du sandbox Cowork une fois (à revérifier au prochain run réel, ce correctif ne résout que l'étape de dépôt, pas celle de téléchargement si elle est encore bloquée). |

### Colonnes de la sheet "Matchs" (ordre exact, A → AF)

```
Code Gesthand, Catégorie, Genre, Index, Championnat, Poule, Journée,
Eq1, Eq1X, Date, Heure, Eq2, Eq2X, Gymnase, Ville,
Eq1Score, Eq2Score, WinLose,
Story Insta, Get Story, Story avant match, Publier Story, Lien Story,
PhotoEq, Story résultat,
INSTA_Cat, INSTA_date, INSTA_Eq1, INSTA_Eq2, Insta_Ville,
Score Source, Commentaire
```

- `Code Gesthand` = l'ID FFHB (`rencontre-XXXXXXX`, extrait du lien scrapé)
  pour les matchs venant du scraper. Les matchs ajoutés à la main gardent le
  format historique de Julien (date + indice, ex. `1309E` — **pas** un vrai
  code Gesthand malgré le nom de la colonne, un identifiant qu'il invente
  lui-même).
- `Eq1`/`Eq2` : le côté qui est nous reçoit le nom de section du club (propre,
  ex. `Entente Villette Genas`) + `Eq1X`/`Eq2X` = notre `indice` (A/B/C...,
  vide si l'équipe est seule dans sa catégorie). Le côté adverse reçoit le
  nom FFHB brut (souvent un peu bruité, ex. `M18F EXC - ENTENTE LYON EST
  HANDBALL - 1`) ; `split_trailing_index()` (Python, scraper) tente d'en
  extraire un indice en suffixe (` - 1`, ` 2`...) quand il y en a un —
  **note** : cette fonction ne nettoie que l'indice, pas le préfixe de
  poule ; le nettoyage complet (préfixe + indice) affiché côté site utilise
  `cleanOpponentLabel` en JS (`index.html`), une logique distincte non
  répercutée dans la sheet elle-même.
- `Date`/`Heure` ne sont écrites **que si FFHB a confirmé la date** (présence
  de l'heure dans le texte scrapé) — jamais une date approximative/plage.
- `Eq1Score`/`Eq2Score`/`WinLose` : par le scraper, seulement si FFHB
  affiche un score (`WinLose` calculé du point de vue du club :
  Victoire/Défaite/Match Nul, pas juste "qui a gagné dans l'absolu") ; par le
  formulaire club, à chaque saisie tant que non verrouillé (voir `Score
  Source`). Le scraper marque aussi `Score Source='ffhb'` dès qu'il écrit un
  score — **verrouille alors la saisie manuelle** côté formulaire
  (`updateScore` refuse toute modification de score, correction éventuelle
  directement dans la sheet). Le formulaire manuel marque `Score
  Source='manuel'`.
- `PhotoEq` : lien de la photo "officielle" (réseaux) — écrit uniquement par
  `select_photo` (sélection manuelle depuis la page match), plus par
  `add_photo` directement.
- `Commentaire` : texte libre saisi depuis la page match, jamais verrouillé
  même si le score l'est.
- `Story Insta`/`Get Story`/`Story avant match`/`Publier Story`/`Lien Story`
  (pilotage de publication, hérité d'un ancien flux Make) : **toujours
  orphelines**, jamais touchées par le scraper ni par les actions
  ci-dessus, mécanisme de remplissage d'origine non identifié — ne pas s'y
  fier ni les réutiliser sans vérifier au cas par cas.
- `Story résultat` : **réutilisée depuis le 2026-08-17** (accord explicite
  de Julien) comme marqueur "story résultat déjà générée" pour
  l'automatisation Canva (voir action `mark_story_done` ci-dessus) — ce
  n'est plus une colonne orpheline, ne pas la confondre avec les
  `Story*` toujours mortes listées juste au-dessus.
- `INSTA_Cat`/`INSTA_date`/`INSTA_Eq1`/`INSTA_Eq2`/`Insta_Ville` : remplies
  **uniquement à la création** de la ligne par le scraper (pensées à
  l'origine pour un futur Canva Bulk Create), jamais réécrites ensuite —
  voir "Prochaine étape" en tête de ce fichier.

### Historique : migration depuis Make.com (terminée)

Le club utilisait 3 repos (`form-score-club`, `form-score-club-2-`,
`form-score-club-photo-only`) pilotés par des scénarios Make.com + stockage
Dropbox pour la saisie score/photo en direct. **Cette migration est
terminée** : `form-score-club-2-` utilise maintenant exclusivement ce Web
App (voir section dédiée plus bas), Make.com et Dropbox ne sont plus
utilisés pour ce flux. `form-score-club-photo-only` est **retiré**
(fonctionnalité absorbée par la page match unifiée) — repo laissé tel quel
sur GitHub mais plus lié depuis le site, plus maintenu.
`form-score-club` (plan Supabase/dashboard/PWA plus large, resté au stade
"session 1/6") reste un chantier séparé, sans lien avec ce qui précède, pas
touché dans ce projet.

## `form-score-club-2-` — saisie score/photo/commentaire en direct

Repo séparé : `sportingvillette/sportingvillette.github.io`
(renommé le 2026-08-26, ex `form-score-club-2-`, pour obtenir une URL
courte sans dépendre du domaine `sportingvillette.com` délégué à
SportsRégions — clone local resté au chemin/nom `form-score-club-2-` par
commodité), même workflow de collaboration (branche/PR/"ON MERGE").
Hébergé sur GitHub Pages : `https://sportingvillette.github.io/`.
Fichier unique `index.html`, même philosophie que `sv-planning-entrainements`
(pas de build, pas de dépendance externe).

### Deux vues dans la même page, pilotées par `?match_id=`

- **Sans le paramètre** : liste des rencontres. Sélecteur de week-end en
  haut (par défaut le week-end en cours/à venir), matchs groupés par jour,
  cadenas 🔒 sous l'heure si le score est déjà verrouillé (FFHB). Un champ
  "ID match" manuel + bouton "Ouvrir" sert de filet de sécurité si un match
  n'apparaît pas dans la liste. Cliquer une carte navigue vers
  `?match_id=XXX` (vraie navigation, pas de routing JS côté client) — donne
  au passage un lien partageable/bookmarkable par match.
- **Avec le paramètre** : page dédiée à ce match. Recharge les données
  depuis le CSV publié à chaque chargement (pas de state partagé entre
  vues). Contient :
  - **Score en direct** : steppers +/- (pas de saisie clavier) pour le
    score domicile/extérieur et le temps de jeu, "État du match"
    (Terminé/En cours). Chaque tap envoie automatiquement après ~600ms
    d'inactivité (debounce, évite de spammer le Web App) — pas de bouton
    "Envoyer". Désactivé (grisé) si le score est verrouillé, avec message
    explicite.
  - **Commentaire** : `<textarea>`, même mécanique d'envoi auto débouncé,
    **jamais désactivé** même si le score est verrouillé.
  - **Galerie photo** : liste toutes les photos déjà envoyées pour ce match
    (`list_photos`), avec la photo officielle marquée "⭐ Officielle" et un
    lien "Choisir comme officielle" sur les autres. "Ajouter une photo"
    (dropzone, clic ou glisser-déposer) uploade sans désigner automatiquement
    de photo officielle — sélection toujours manuelle. Chargement de la
    galerie avec retry automatique (jusqu'à 3 tentatives, ~1,5s d'écart) +
    bouton "Réessayer" manuel si ça persiste (cf leçon flakiness Apps
    Script) ; même pattern de bouton "Réessayer" sur upload/sélection en
    cas d'échec.
- **Statut d'un match verrouillé** : déterminé côté client à partir de la
  colonne `Score Source` du CSV publié (`'ffhb'` → verrouillé). Le serveur
  (`updateScore` dans `Code.gs`) revérifie et refuse aussi toute tentative
  de modification du score si verrouillé — défense en profondeur, pas
  seulement une UX côté client.

### Notes d'implémentation utiles

- `CONFIG.fields` (en tête du `<script>`) fait le mapping nom de champ JS →
  en-tête exact de colonne CSV — à tenir à jour si une colonne de la sheet
  est renommée.
- Toutes les requêtes d'écriture passent par `CONFIG.webhookUrl` +
  `CONFIG.webhookSecret` (= `FORM_SHARED_SECRET` de `Code.gs`) — à
  resynchroniser si le secret change côté Apps Script.
- Donnée de test à surveiller/nettoyer si besoin : le match `AMAB3` (poule
  "Tournoi Amical", donc sans enjeu réel) porte des photos et un commentaire
  de test posés pendant le développement de la galerie/commentaire — jamais
  nettoyés, à faire si ça gêne (ou laisser, c'est un match fictif).

## Automatisation SportsRégions (fiches équipe + illustrations)

Les 37 équipes de la saison 2026-2027 ont une fiche SportsRégions complète
(planning, entraîneurs, championnat + lien FFHB, logo de section, nom
d'équipe) générée et maintenue par automatisation plutôt que saisie manuelle.

**Répartition du code (attention, pas tout dans ce repo)** :
- `renderEquipeFicheSportsRegions(r)` dans `index.html` — génère le bloc
  HTML "safe" à coller dans le champ CKEditor "Présentation de l'équipe"
  (mêmes contraintes que `renderEquipeMinimal` : seuls `<br>/<b>/<i>` +
  `style="color:.../background-color:..."` survivent au filtrage de
  l'éditeur — **mais** les attributs HTML `border`/`cellpadding`/`cellspacing`
  d'un `<table>`, et les liens `<a href>`, survivent aussi, confirmé en
  prod). **Sur la branche `feature/fiche-equipe-sportsregions`, jamais
  mergée/pushée** — à récupérer avant de continuer ce chantier
  (`git log`/`git diff` sur cette branche localement).
- `sportsregions_pipeline.py` + `sportsregions_creds.py` — **dans le dossier
  `97 - python` (repo AT4 séparé, PAS dans `sv-planning-entrainements`)**, à
  côté de `vpn_connect.py`/`shippingbo_pipeline.py`. Playwright pilote
  `admin.sportsregions.fr` (login+2FA, création/modif d'équipe, upload
  illustration). Identifiants dans le coffre Windows (`keyring`, service
  `AT4_SportsRegions`).

**Points techniques importants (à ne pas redécouvrir)** :
- `admin.sportsregions.fr` est un **sous-domaine à session séparée** de
  `sportingvillette.com` — toute navigation doit passer par le pont SSO
  `https://www.sportingvillette.com/login/go?l=<url encodée>`
  (`admin_bridge()` dans le script), sinon on retombe sur un formulaire de
  login admin distinct.
- **2FA au premier login** d'une session Playwright (probablement une
  vérif "nouvel appareil", pas une 2FA de compte à proprement parler) —
  contournée en sauvegardant `context.storage_state()` après un premier
  login **headed** (fenêtre visible, code tapé par Julien) ; les runs
  suivants réutilisent la session sans 2FA. **La session expire assez vite
  (observé : de ~10 min à quelques heures selon les runs)** — si un script
  échoue avec "Session SportsRégions expirée", relancer
  `python sportsregions_pipeline.py --login-test`.
- Convention de nommage des équipes : `{Catégorie}{Genre} {Indice}`, genre
  (`F`/`G`, rien si Mixte/vide) **accolé sans espace** à la catégorie,
  indice séparé par un espace (ex. `M11F A`, `M18G CF`, `LoisirG`,
  `Handfit`). `Seniors` abrégé en `S` (donc `SF`/`SG`). Toujours encoder le
  genre dans le nom, même sans risque de collision apparent — élimine
  structurellement toute ambiguïté entre sections.
- Table admin `/groupe` : le nom d'équipe est dans `td.titre`/`td.ellipsis`,
  **pas le premier `<td>`** (une colonne case-à-cocher a été ajoutée par
  SportsRégions à un moment donné, cassant un sélecteur naïf) —
  `find_team_id()` cible `td.titre, td.ellipsis` spécifiquement.
- Upload de la "Photo de l'équipe" = vrai upload de fichier via
  `#file_upload_component_illustration` (`page.set_input_files`), pas une
  URL — `upload_illustration()` dans le script.

**Illustration (logo + nom d'équipe) via Canva** :
- Connecteur Canva MCP piloté **interactivement en session** (pas de script
  Python autonome) : `copy-design` du modèle maître "Modèle logo équipe"
  (`DAHSSrVYMtE`, dossier Canva "Claude") → `edit-design` (redimensionner le
  cadre logo selon le ratio de la section pour "contenir" sans rogner,
  remplir avec le bon logo, remplacer le texte par le nom d'équipe) →
  `export-design` PNG 1200×800 → upload via `sportsregions_pipeline.py`.
- 4 logos de section identifiés dans Canva (asset IDs et tailles de cadre
  "contenant" par section — SV, EVG, ELEH, EEL) — voir les designs déjà
  générés dans le dossier "Claude" si besoin de retrouver les asset IDs
  (ou redemander à Julien le lien du dossier de logos).
- **⚠️ Bug Canva confirmé, à surveiller sur tout futur lot** :
  `export-design` appelé juste après un `edit-design(finalize:"commit")` sur
  une copie structurellement identique à d'autres (même template recopié
  plusieurs fois) peut renvoyer le **contenu d'un design voisin** généré à
  peu près au même moment, silencieusement. Un lot de 36 exports a eu 3
  erreurs de ce type, détectées uniquement en **regardant chaque image
  téléchargée avant de l'uploader** — pas de méthode automatique fiable
  trouvée. Toujours vérifier visuellement avant upload, surtout sur un gros
  lot.
- Le connecteur Canva n'a pas d'outil de suppression — nettoyer le dossier
  "Claude" (designs de travail, un par équipe générée) se fait manuellement
  par Julien dans l'UI Canva si besoin.

## Roadmap (état à date, pour la suite)

1. ~~**Migrer score/photo vers le Web App Apps Script**~~ — **fait**, voir
   sections ci-dessus (`Code.gs` + page match unifiée `form-score-club-2-`).
2. ~~**Explorer l'exploitation des données dans d'autres outils : Canva,
   SportsRégions, etc.**~~ — **fiches équipe + illustrations faites**, voir
   section dédiée "Automatisation SportsRégions" ci-dessus. Suite possible,
   pas commencée : import du calendrier des matchs sur SportsRégions
   (`admin.sportsregions.fr/evenement`, import CSV repéré mais jamais
   exploré — limite connue : ajoute seulement, ne supprime jamais).
3. **Résumé PDF hebdomadaire** ("Journal L'Équipe du week-end" dans les
   discussions précédentes) — bilan des matchs joués/gagnés/perdus + photos
   + commentaires, généré automatiquement par cron nocturne, lien de
   téléchargement sur le site le lundi matin (décision déjà prise avec
   Julien : lien sur le site, pas d'email). L'infrastructure préalable
   (commentaire + galerie photo) est **construite** ; la génération PDF
   elle-même (probablement Playwright en CI, `page.pdf()`, réutilisant le
   pattern `window.print()`/`@media print` déjà validé) **n'est pas
   commencée**.
4. **Sponsors** : bandeau/pied de page réutilisable sur les futures vues.
   Pas encore de source de données identifiée pour la liste de sponsors —
   à demander à Julien avant de construire.
5. **Dashboard live pour les licenciés** (lecture simple de `data/*.csv`,
   pas de nouvelle donnée à collecter).
6. **Écran TV au gymnase** — variante plein écran/auto-refresh du
   dashboard ci-dessus.
7. **Outil d'aide à la planification** — un vrai projet à part, décrit en
   détail par Julien : (a) déterminer quels matchs sont à domicile pour le
   club, sachant que pour une entente il faut d'abord s'accorder entre
   clubs membres sur qui reçoit ; (b) construire un planning de week-end en
   croisant avec les disponibilités des gymnases (sheet dédié existant,
   colonnes `E1..E4.Lieu/Jour/Debut/Fin` du sheet équipes) ; (c) suggérer
   des horaires (échauffement + durée de match connus) avant validation
   définitive dans Gesthand → remontée sur ffhandball.fr → captée par notre
   scraper. Explicitement mis de côté par Julien pour plus tard.
