/**
 * Web App unique pour Sporting Villette : reçoit les matchs ajoutés/mis à jour par le
 * scraper FFHB (action "add_match"), et remplace maintenant aussi les 2 scénarios Make.com
 * des formulaires club (action "add_score" pour le score en direct, "add_photo" pour la
 * photo de fin de match, uploadée sur Google Drive à la place de Dropbox).
 *
 * Les formulaires (form-score-club-2-, form-score-club-photo-only) sont des pages HTML
 * publiques : ils postent en multipart/form-data (pas de JSON) et utilisent un secret
 * DIFFÉRENT de celui du scraper (FORM_SHARED_SECRET, moins sensible) pour que sa fuite
 * éventuelle dans ce code JS public ne compromette pas SHARED_SECRET (utilisé par le
 * scraper côté GitHub Actions, jamais exposé).
 *
 * MISE À JOUR (cas normal — ce Web App est déjà déployé en prod pour le scraper FFHB,
 * l'URL /exec existe déjà et est en dur dans index.html + les 2 repos formulaires) :
 * 0) Si ce n'est pas déjà fait : dans la feuille "Matchs", ajouter 2 colonnes tout à la fin
 *    (après Insta_Ville) — "Score Source" (colonne AE, verrouille la saisie manuelle du
 *    score une fois confirmé par le scraper FFHB) puis "Commentaire" (colonne AF, texte
 *    libre saisi depuis la page match, toujours modifiable même si le score est verrouillé).
 * 1) Ouvrir le Google Sheet "Com matchs réseaux" > Extensions > Apps Script.
 * 2) Coller ce fichier (remplace le contenu de Code.gs).
 * 3) Remplacer SHARED_SECRET et FORM_SHARED_SECRET ci-dessous par deux valeurs
 *    secrètes distinctes de ton choix (garder la même valeur pour SHARED_SECRET que
 *    celle déjà utilisée si tu ne veux pas casser le scraper existant).
 * 4) Créer un dossier Google Drive "Photos matchs" (sur le compte associatif), ouvrir
 *    son ID dans l'URL (drive.google.com/drive/folders/<ID>) et le coller dans
 *    PHOTOS_FOLDER_ID ci-dessous.
 * 5) Exécuter manuellement n'importe quelle fonction depuis l'éditeur (bouton "Exécuter",
 *    n'importe laquelle dans le menu déroulant) — Drive est un nouveau service pour ce
 *    projet, ça déclenche l'écran d'autorisation. Accepter l'accès Drive avec le compte
 *    propriétaire du Sheet. Sans ça, add_photo échoue avec "Vous n'êtes pas autorisé à
 *    appeler DriveApp...", même après un redéploiement.
 * 6) Déployer > Gérer les déploiements > éditer (icône crayon) > Nouvelle version.
 *    NE PAS faire "Nouveau déploiement" ici : ça changerait l'URL /exec et casserait
 *    le scraper + le site + les formulaires qui ont tous l'ancienne URL en dur.
 * 7) Dans form-score-club-2-/index.html et form-score-club-photo-only/index.html,
 *    mettre à jour CONFIG.webhookSecret avec la même valeur que FORM_SHARED_SECRET
 *    ci-dessus (CONFIG.webhookUrl ne change pas, cf point 6).
 *
 * PREMIER DÉPLOIEMENT (seulement si ce Web App n'existe pas encore, ex. nouveau club
 * qui reprendrait ce projet) : étapes 1 à 4 ci-dessus, puis Déployer > Nouveau
 * déploiement > Type "Application Web" (Exécuter en tant que : Moi ; Qui a accès :
 * Tout le monde), copier l'URL /exec obtenue, et la reporter dans le repo GitHub
 * (Settings > Secrets and variables > Actions : SHEET_WEBAPP_URL + SHEET_WEBAPP_SECRET
 * = SHARED_SECRET) ainsi que dans CONFIG.webhookUrl des 2 repos formulaires.
 */

const SHEET_NAME = 'Matchs';
const SHARED_SECRET = '7x!K9#vP2$mQ8%rL4*'; // remplacer avant déploiement — scraper uniquement
const FORM_SHARED_SECRET = 'wpFt6IaS4QDZCodB'; // remplacer avant déploiement — formulaires publics uniquement
const PHOTOS_FOLDER_ID = '1gwZToQYNPgDnDusnAAQtuHbff5fzPjTK'; // ID du dossier Drive "Photos matchs"
const WEEKEND_POSTS_FOLDER_ID = '14eYhIkOoWk_zEX4T3_r9E6j8cPHHHo78'; // ID du dossier Drive "Temp posts Instagram"
const RESULT_STORIES_FOLDER_ID = '1jR0mMICjSh32KhQhckiXwQiiGZBrwJFv'; // ID du dossier Drive "Temp stories Instagram"
const PROGRESS_CACHE_KEY = 'scrape_progress';
const PROGRESS_CACHE_KEY_SPORTSREGIONS = 'sportsregions_progress'; // clé distincte du scraper FFHB, même mécanisme
const PROGRESS_CACHE_TTL = 21600; // 6h (max autorisé par CacheService)

// Ordre exact des colonnes du Sheet (A -> AF). Ne pas réordonner sans adapter le Sheet.
const COLUMNS = [
  'Code Gesthand', 'Catégorie', 'Genre', 'Index', 'Championnat', 'Poule', 'Journée',
  'Eq1', 'Eq1X', 'Date', 'Heure', 'Eq2', 'Eq2X', 'Gymnase', 'Ville',
  'Eq1Score', 'Eq2Score', 'WinLose',
  'Story Insta', 'Get Story', 'Story avant match', 'Publier Story', 'Lien Story',
  'PhotoEq', 'Story résultat',
  'INSTA_Cat', 'INSTA_date', 'INSTA_Eq1', 'INSTA_Eq2', 'Insta_Ville',
  'Score Source', // 'ffhb' (confirmé par le scraper, verrouille la saisie manuelle) ou 'manuel'
  'Commentaire', // texte libre, saisi depuis la page match, jamais verrouillé
];

const JOURS_FR = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];

function doPost(e) {
  try {
    // Les formulaires club (score/photo) postent en multipart/form-data (nécessaire pour
    // envoyer un fichier) : les champs arrivent dans e.parameter, pas e.postData.contents.
    // Pour une requête multipart, Apps Script ne peuple pas forcément e.postData (contents
    // undefined) — on ne passe donc par le parsing JSON que si le type est explicitement
    // application/json (seul le scraper, JSON classique, envoie ce type) ; tout le reste
    // est traité comme des champs de formulaire (e.parameter).
    const isJson = e.postData && e.postData.type === 'application/json';

    if (!isJson) {
      const p = e.parameter;
      if (p.secret !== FORM_SHARED_SECRET) {
        return jsonResponse({ ok: false, error: 'secret invalide' });
      }
      if (p.action === 'add_score') return jsonResponse(updateScore(p));
      if (p.action === 'add_photo') return jsonResponse(addPhoto(p));
      if (p.action === 'select_photo') return jsonResponse(selectPhoto(p));
      if (p.action === 'delete_photo') return jsonResponse(deletePhoto(p));
      if (p.action === 'mark_story_done') return jsonResponse(markStoryDone(p));
      if (p.action === 'add_asset') return jsonResponse(addAsset(p));
      if (p.action === 'save_amical_match') return jsonResponse(saveAmicalMatch(p));
      return jsonResponse({ ok: false, error: 'action inconnue: ' + p.action });
    }

    const body = JSON.parse(e.postData.contents);
    if (body.secret !== SHARED_SECRET) {
      return jsonResponse({ ok: false, error: 'secret invalide' });
    }
    if (body.action === 'add_match') {
      return jsonResponse(upsertMatch(body.match));
    }
    if (body.action === 'progress') {
      // Suivi d'avancement d'un run de scraping — stockage éphémère (CacheService,
      // pas le Sheet), lu par le site via doGet pour afficher une barre de progression.
      CacheService.getScriptCache().put(PROGRESS_CACHE_KEY, JSON.stringify(body.progress), PROGRESS_CACHE_TTL);
      return jsonResponse({ ok: true });
    }
    if (body.action === 'progress_sportsregions') {
      // Même mécanique que 'progress' (scraper FFHB) mais clé de cache distincte — suivi de
      // scripts/push_sportsregions_fiches.py (workflow GitHub Actions "Mise à jour SportsRégions").
      CacheService.getScriptCache().put(PROGRESS_CACHE_KEY_SPORTSREGIONS, JSON.stringify(body.progress), PROGRESS_CACHE_TTL);
      return jsonResponse({ ok: true });
    }
    return jsonResponse({ ok: false, error: 'action inconnue: ' + body.action });
  } catch (err) {
    return jsonResponse({ ok: false, error: String(err) });
  }
}

// Lecture de la progression / de la galerie photo (pas d'authentification requise — données
// non sensibles : les photos sont déjà partagées "anyone with link", et le match_id n'a rien
// de secret).
function doGet(e) {
  if (e.parameter.action === 'progress') {
    const raw = CacheService.getScriptCache().get(PROGRESS_CACHE_KEY);
    return jsonResponse(raw ? JSON.parse(raw) : null);
  }
  if (e.parameter.action === 'progress_sportsregions') {
    const raw = CacheService.getScriptCache().get(PROGRESS_CACHE_KEY_SPORTSREGIONS);
    return jsonResponse(raw ? JSON.parse(raw) : null);
  }
  if (e.parameter.action === 'list_photos') {
    return jsonResponse(listPhotos(e.parameter.match_id));
  }
  if (e.parameter.action === 'list_amicaux') {
    return jsonResponse(listAmicaux());
  }
  return jsonResponse({ ok: false, error: 'action inconnue' });
}

function getSheet() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('Feuille "' + SHEET_NAME + '" introuvable');
  return sheet;
}

// Colonne A = Code Gesthand. Recherche linéaire (volume de matchs d'un club : pas un
// problème de perf tant qu'on reste sous quelques milliers de lignes).
function findRowByCode(sheet, code) {
  const data = sheet.getRange(1, 1, sheet.getLastRow(), 1).getValues();
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]).trim() === String(code).trim()) return i + 1; // numéro de ligne 1-indexé
  }
  return null;
}

function colIndex(name) {
  const idx = COLUMNS.indexOf(name);
  if (idx === -1) throw new Error('Colonne inconnue: ' + name);
  return idx;
}

/**
 * Ajoute ou met à jour un match par Code Gesthand (= ID FFHB pour les matchs scrapés).
 * Ne touche jamais aux colonnes de suivi de publication (Story*, PhotoEq) sur une ligne
 * existante — seulement les champs sourcés FFHB. Les colonnes INSTA_* ne sont remplies
 * qu'à la création (aide manuelle pour Canva), jamais réécrites ensuite.
 */
function upsertMatch(m) {
  if (!m || !m.code) return { ok: false, error: 'match.code manquant' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, m.code);

  const values = {
    'Code Gesthand': m.code,
    'Catégorie': m.categorie || '',
    'Genre': m.genre || '',
    'Index': m.index || '',
    'Championnat': m.championnat || '',
    'Poule': m.poule || '',
    'Journée': m.journee || '',
    'Eq1': m.eq1 || '',
    'Eq1X': m.eq1x || '',
    'Eq2': m.eq2 || '',
    'Eq2X': m.eq2x || '',
    'Gymnase': m.gymnase || '',
    'Ville': m.ville || '',
  };
  // Date/Heure : n'écrase que si le scraper envoie une date confirmée (sinon on garde
  // ce qui était déjà là, potentiellement une date confirmée entre-temps par un autre run).
  if (m.date) values['Date'] = m.date;
  if (m.heure) values['Heure'] = m.heure;
  // Score/WinLose : n'écrase que si FFHB a publié un score (source de vérité, voir CLAUDE.md).
  // Marque aussi Score Source='ffhb', qui verrouille la saisie manuelle côté formulaire club
  // (cf updateScore) — un score FFHB est définitif, une correction éventuelle se fait
  // directement dans la sheet, pas via le formulaire.
  if (m.eq1score !== undefined && m.eq1score !== '') values['Eq1Score'] = m.eq1score;
  if (m.eq2score !== undefined && m.eq2score !== '') values['Eq2Score'] = m.eq2score;
  if (m.winlose) values['WinLose'] = m.winlose;
  if ((m.eq1score !== undefined && m.eq1score !== '') || (m.eq2score !== undefined && m.eq2score !== '')) {
    values['Score Source'] = 'ffhb';
  }

  if (rowNumber) {
    const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
    const current = rowRange.getValues()[0];
    Object.keys(values).forEach(col => {
      current[colIndex(col)] = values[col];
    });
    rowRange.setValues([current]);
    return { ok: true, action: 'updated', row: rowNumber };
  }

  const newRow = COLUMNS.map(col => (Object.prototype.hasOwnProperty.call(values, col) ? values[col] : ''));
  newRow[colIndex('INSTA_Cat')] = [m.categorie, m.genre].filter(Boolean).join(' ');
  newRow[colIndex('INSTA_date')] = formatInstaDate(m.date, m.heure);
  newRow[colIndex('INSTA_Eq1')] = m.eq1 || '';
  newRow[colIndex('INSTA_Eq2')] = m.eq2 || '';
  newRow[colIndex('Insta_Ville')] = m.ville || '';

  sheet.appendRow(newRow);
  return { ok: true, action: 'inserted' };
}

// Une cellule "Date"/"Heure" peut revenir en objet Date natif de Google Sheets (si la
// colonne a été auto-formatée en date par Sheets à un moment) ou en simple chaîne (si jamais
// reformatée) — jamais garanti dans un sens ou l'autre selon comment la ligne a été créée
// (script vs saisie manuelle dans l'UI Sheets). Toujours passer par ces 2 fonctions avant de
// renvoyer une date/heure au client, jamais supposer un type précis.
function formatDateDDMMYYYY(v) {
  if (Object.prototype.toString.call(v) === '[object Date]') {
    return Utilities.formatDate(v, Session.getScriptTimeZone(), 'dd/MM/yyyy');
  }
  return String(v || '').trim();
}
function formatHeureHHMM(v) {
  if (Object.prototype.toString.call(v) === '[object Date]') {
    return Utilities.formatDate(v, Session.getScriptTimeZone(), 'HH:mm');
  }
  return String(v || '').trim();
}

/**
 * Liste tous les matchs marqués journée="Amical" — alimente le sélecteur "modifier un match
 * amical" de index.html (mode light comme admin). Lecture seule, pas d'authentification
 * requise (même principe que list_photos/progress : rien de sensible, juste les infos déjà
 * publiques du calendrier club).
 */
function listAmicaux() {
  const sheet = getSheet();
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return { ok: true, matches: [] };
  const data = sheet.getRange(1, 1, lastRow, COLUMNS.length).getValues();
  const matches = [];
  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    if (String(row[colIndex('Journée')]).trim().toLowerCase() !== 'amical') continue;
    const date = formatDateDDMMYYYY(row[colIndex('Date')]);
    matches.push({
      code: row[colIndex('Code Gesthand')],
      categorie: row[colIndex('Catégorie')],
      genre: row[colIndex('Genre')],
      indice: row[colIndex('Index')],
      eq1: row[colIndex('Eq1')],
      eq2: row[colIndex('Eq2')],
      date: date,
      heure: formatHeureHHMM(row[colIndex('Heure')]),
      gymnase: row[colIndex('Gymnase')],
      ville: row[colIndex('Ville')],
      score1: row[colIndex('Eq1Score')],
      score2: row[colIndex('Eq2Score')],
      // AAAA-MM-JJ pour un tri chronologique correct côté client (le format DD/MM/YYYY ne
      // se trie pas correctement en simple comparaison de chaînes).
      date_sort: date.split('/').reverse().join('-'),
    });
  }
  return { ok: true, matches: matches };
}

/**
 * Ajoute ou modifie un match AMICAL — formulaire public (index.html, ?mode=light ou admin),
 * FORM_SHARED_SECRET (voir doPost). Jamais pour un vrai match FFHB : une modification
 * (code fourni) est refusée si la ligne visée n'est pas déjà journée="Amical" — empêche un
 * formulaire public de altérer un match officiel. Un ajout (pas de code) force toujours
 * journée="Amical" et Championnat="Tournoi amical", quoi que le client envoie.
 */
function saveAmicalMatch(p) {
  if (!p.categorie) return { ok: false, error: 'catégorie manquante' };
  if (!p.eq1 || !p.eq2) return { ok: false, error: 'les 2 équipes sont requises' };
  if (!p.date || !p.heure) return { ok: false, error: 'date/heure requises' };

  const sheet = getSheet();
  const code = (p.code || '').trim();

  if (code) {
    const rowNumber = findRowByCode(sheet, code);
    if (!rowNumber) return { ok: false, error: 'match introuvable: ' + code };
    const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
    const current = rowRange.getValues()[0];
    if (String(current[colIndex('Journée')]).trim().toLowerCase() !== 'amical') {
      return { ok: false, error: "ce match n'est pas un amical — modification refusée" };
    }
    current[colIndex('Catégorie')] = p.categorie;
    current[colIndex('Genre')] = p.genre || '';
    current[colIndex('Index')] = p.indice || '';
    current[colIndex('Eq1')] = p.eq1;
    current[colIndex('Eq2')] = p.eq2;
    current[colIndex('Date')] = p.date;
    current[colIndex('Heure')] = p.heure;
    current[colIndex('Gymnase')] = p.gymnase || '';
    current[colIndex('Ville')] = p.ville || '';
    if (p.score1 !== undefined && p.score1 !== '') current[colIndex('Eq1Score')] = p.score1;
    if (p.score2 !== undefined && p.score2 !== '') current[colIndex('Eq2Score')] = p.score2;
    rowRange.setValues([current]);
    return { ok: true, action: 'amical_updated', code: code };
  }

  // Nouveau match : code déterministe (même convention que les amicaux déjà saisis à la
  // main), garanti unique par suffixe -2/-3... en cas de collision.
  const slug = String(p.ville || 'MATCH').trim().toUpperCase().replace(/[^A-Z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'MATCH';
  const dateParts = String(p.date).split('/'); // DD/MM/YYYY
  const dateSlug = dateParts.length === 3 ? dateParts[2] + dateParts[1] + dateParts[0] : String(p.date).replace(/\D/g, '');
  const heureSlug = String(p.heure).replace(':', 'H');
  const base = `AMICAL-${slug}-${dateSlug}-${heureSlug}`;
  let newCode = base;
  let n = 2;
  while (findRowByCode(sheet, newCode)) { newCode = `${base}-${n}`; n++; }

  const values = {
    'Code Gesthand': newCode, 'Catégorie': p.categorie, 'Genre': p.genre || '', 'Index': p.indice || '',
    'Championnat': 'Tournoi amical', 'Journée': 'Amical',
    'Eq1': p.eq1, 'Eq2': p.eq2, 'Date': p.date, 'Heure': p.heure,
    'Gymnase': p.gymnase || '', 'Ville': p.ville || '',
  };
  if (p.score1 !== undefined && p.score1 !== '') values['Eq1Score'] = p.score1;
  if (p.score2 !== undefined && p.score2 !== '') values['Eq2Score'] = p.score2;

  const newRow = COLUMNS.map(col => (Object.prototype.hasOwnProperty.call(values, col) ? values[col] : ''));
  newRow[colIndex('INSTA_Cat')] = [p.categorie, p.genre].filter(Boolean).join(' ');
  newRow[colIndex('INSTA_date')] = formatInstaDate(p.date, p.heure);
  newRow[colIndex('INSTA_Eq1')] = p.eq1;
  newRow[colIndex('INSTA_Eq2')] = p.eq2;
  newRow[colIndex('Insta_Ville')] = p.ville || '';

  sheet.appendRow(newRow);
  return { ok: true, action: 'amical_inserted', code: newCode };
}

/**
 * Formulaire score en direct (remplace le scénario Make "Formulaire nouveau score",
 * route "sans photo" — la route "avec photo_finale" était du code mort, non reproduite).
 * Écrase toujours Eq1Score/Eq2Score/WinLose : contrairement au scraper, ici c'est une
 * saisie humaine explicite, donc source de vérité la plus récente — SAUF si le score a déjà
 * été confirmé par le scraper FFHB (Score Source='ffhb'), auquel cas la modification
 * manuelle est bloquée (verrou strict ; correction éventuelle directement dans la sheet).
 * Le commentaire (p.commentaire), lui, reste modifiable même si le score est verrouillé —
 * la page match envoie donc les champs score_dom/score_ext/winlose UNIQUEMENT quand la
 * modification du score est autorisée côté client (sinon elle n'envoie que le commentaire).
 */
function updateScore(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (!rowNumber) return { ok: false, error: 'match introuvable: ' + p.match_id };

  const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
  const current = rowRange.getValues()[0];
  const locked = current[colIndex('Score Source')] === 'ffhb';
  const wantsScoreChange = p.score_dom !== undefined || p.score_ext !== undefined || p.winlose !== undefined;

  if (locked && wantsScoreChange) {
    return { ok: false, error: 'Score déjà confirmé par la FFHB — modification manuelle bloquée.' };
  }
  if (wantsScoreChange) {
    if (p.score_dom !== undefined && p.score_dom !== '') current[colIndex('Eq1Score')] = p.score_dom;
    if (p.score_ext !== undefined && p.score_ext !== '') current[colIndex('Eq2Score')] = p.score_ext;
    if (p.winlose) current[colIndex('WinLose')] = p.winlose;
    current[colIndex('Score Source')] = 'manuel';
  }
  if (p.commentaire !== undefined) current[colIndex('Commentaire')] = p.commentaire;
  rowRange.setValues([current]);
  return { ok: true, action: 'score_updated', row: rowNumber };
}

/**
 * Formulaire photo (remplace les 2 scénarios Make qui uploadaient sur Dropbox sans jamais
 * écrire dans la sheet). Upload sur Drive (dossier dédié par match) — alimente la galerie
 * de la page match, mais n'écrit PLUS PhotoEq directement : plusieurs photos peuvent
 * s'accumuler pour un même match, la photo "officielle" (réseaux) est choisie séparément
 * et explicitement via selectPhoto (sélection manuelle depuis la galerie).
 *
 * La photo arrive en base64 (p.photo_base64 + p.photo_name + p.photo_type), pas en Blob
 * multipart natif : testé en prod, Apps Script ne peuple PAS e.parameter avec un Blob pour
 * un fichier envoyé via un vrai POST multipart/form-data externe (seuls les champs texte
 * arrivent) — contrairement au comportement d'un <input type=file> dans un formulaire
 * HtmlService classique. D'où l'encodage base64 côté client (voir form-score-club-2-).
 *
 * Nécessite le scope Drive en écriture (pas seulement lecture) : après avoir ajouté ce
 * code, il faut exécuter manuellement une fonction du projet une fois depuis l'éditeur
 * Apps Script pour déclencher l'écran d'autorisation et accepter l'accès Drive — sinon
 * le Web App déployé échoue avec "Vous n'êtes pas autorisé à appeler DriveApp...".
 */
function addPhoto(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  if (!p.photo_base64) return { ok: false, error: 'photo manquante' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (!rowNumber) return { ok: false, error: 'match introuvable: ' + p.match_id };

  const bytes = Utilities.base64Decode(p.photo_base64);
  const blob = Utilities.newBlob(bytes, p.photo_type || 'image/jpeg', p.photo_name || (p.match_id + '.jpg'));

  const parentFolder = DriveApp.getFolderById(PHOTOS_FOLDER_ID);
  const matchFolder = getOrCreateSubfolder(parentFolder, p.match_id);
  const file = matchFolder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  const url = 'https://lh3.googleusercontent.com/d/' + file.getId();

  // 1ère photo du match (aucune photo officielle choisie pour l'instant) -> devient
  // automatiquement la photo officielle, pour éviter le clic "Choisir comme officielle"
  // systématique dans le cas le plus courant (une seule photo par match). Les photos
  // suivantes n'écrasent jamais une sélection déjà faite. Demande de Julien, 2026-09-XX.
  const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
  const current = rowRange.getValues()[0];
  let madeOfficial = false;
  if (!current[colIndex('PhotoEq')]) {
    current[colIndex('PhotoEq')] = url;
    rowRange.setValues([current]);
    madeOfficial = true;
  }

  return { ok: true, action: 'photo_added', url: url, fileId: file.getId(), madeOfficial: madeOfficial };
}

/**
 * Supprime définitivement une photo de la galerie d'un match (fichier Drive envoyé à la
 * corbeille) — déclenché par la croix de suppression sur chaque vignette de la galerie,
 * confirmation déjà faite côté client avant l'appel. Si la photo supprimée était la photo
 * officielle (PhotoEq), la colonne est vidée : jamais de lien mort réutilisé ensuite par la
 * news hebdo ou le post Instagram.
 */
function deletePhoto(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  if (!p.photo_url) return { ok: false, error: 'photo_url manquant' };

  const fileId = extractFileIdFromUrl(p.photo_url);
  if (!fileId) return { ok: false, error: 'URL de photo invalide' };
  try {
    DriveApp.getFileById(fileId).setTrashed(true);
  } catch (err) {
    return { ok: false, error: 'Fichier introuvable ou déjà supprimé' };
  }

  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (rowNumber) {
    const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
    const current = rowRange.getValues()[0];
    if (current[colIndex('PhotoEq')] === p.photo_url) {
      current[colIndex('PhotoEq')] = '';
      rowRange.setValues([current]);
    }
  }
  return { ok: true, action: 'photo_deleted' };
}

function extractFileIdFromUrl(url) {
  const m = String(url).match(/\/d\/([^/?]+)/);
  return m ? m[1] : null;
}

/**
 * Marque une photo de la galerie (déjà uploadée via addPhoto) comme LA photo officielle
 * du match (écrit PhotoEq) — sélection manuelle depuis la page match, jamais automatique.
 */
function selectPhoto(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  if (!p.photo_url) return { ok: false, error: 'photo_url manquant' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (!rowNumber) return { ok: false, error: 'match introuvable: ' + p.match_id };

  const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
  const current = rowRange.getValues()[0];
  current[colIndex('PhotoEq')] = p.photo_url;
  rowRange.setValues([current]);
  return { ok: true, action: 'photo_selected', row: rowNumber };
}

/**
 * Marque la story résultat d'un match comme générée (écrit 'Story résultat') — pour que
 * la génération automatique (Cowork, voir scripts/find_result_stories.py) ne retraite pas
 * deux fois le même match. Colonne "Story résultat" auparavant orpheline (héritée d'un
 * ancien flux Make jamais reconnecté) — réutilisée ici avec l'accord explicite de Julien.
 * p.value optionnel (sinon horodatage ISO) pour se laisser la possibilité d'y mettre autre
 * chose qu'un simple horodatage plus tard (ex. un lien) sans changer la signature.
 */
function markStoryDone(p) {
  if (!p.match_id) return { ok: false, error: 'match_id manquant' };
  const sheet = getSheet();
  const rowNumber = findRowByCode(sheet, p.match_id);
  if (!rowNumber) return { ok: false, error: 'match introuvable: ' + p.match_id };

  const rowRange = sheet.getRange(rowNumber, 1, 1, COLUMNS.length);
  const current = rowRange.getValues()[0];
  current[colIndex('Story résultat')] = p.value || new Date().toISOString();
  rowRange.setValues([current]);
  return { ok: true, action: 'story_marked_done', row: rowNumber };
}

/**
 * Dépose un fichier (PNG de post/story Canva) dans un sous-dossier d'un des deux dossiers
 * Drive dédiés (Temp posts Instagram / Temp stories Instagram — mêmes dossiers que ceux
 * visibles dans "Outils informatiques", sur le compte propriétaire de ce script). Générique
 * plutôt qu'une action par pipeline : p.kind sélectionne le dossier racine, p.subfolder
 * regroupe les fichiers d'un même run (ex. le weekend_label pour le post hebdo, le match_id
 * pour une story résultat). Même mécanique base64 qu'addPhoto (voir sa docstring pour le
 * détail du pourquoi base64 plutôt que Blob multipart), même partage "anyone with link" pour
 * que Julien puisse ouvrir le fichier directement depuis le lien renvoyé, sans avoir besoin
 * d'accéder à ce compte Drive lui-même.
 */
function addAsset(p) {
  if (!p.kind) return { ok: false, error: 'kind manquant' };
  if (!p.subfolder) return { ok: false, error: 'subfolder manquant' };
  if (!p.file_base64) return { ok: false, error: 'fichier manquant' };

  const rootFolderId = p.kind === 'weekend_post' ? WEEKEND_POSTS_FOLDER_ID
    : p.kind === 'result_story' ? RESULT_STORIES_FOLDER_ID
    : null;
  if (!rootFolderId) return { ok: false, error: 'kind inconnu: ' + p.kind };

  const bytes = Utilities.base64Decode(p.file_base64);
  const blob = Utilities.newBlob(bytes, p.file_type || 'image/png', p.file_name || 'asset.png');

  const parentFolder = DriveApp.getFolderById(rootFolderId);
  const subfolder = getOrCreateSubfolder(parentFolder, p.subfolder);
  const file = subfolder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  const url = 'https://lh3.googleusercontent.com/d/' + file.getId();

  return { ok: true, action: 'asset_added', url: url, fileId: file.getId() };
}

/**
 * Liste toutes les photos déjà uploadées pour un match (dossier Drive dédié) — alimente la
 * galerie de la page match. Retourne une liste vide (pas une erreur) si le dossier n'existe
 * pas encore (aucune photo envoyée pour ce match).
 */
function listPhotos(matchId) {
  if (!matchId) return { ok: false, error: 'match_id manquant' };
  try {
    const parentFolder = DriveApp.getFolderById(PHOTOS_FOLDER_ID);
    const existing = parentFolder.getFoldersByName(String(matchId).trim());
    if (!existing.hasNext()) return { ok: true, photos: [] };
    const matchFolder = existing.next();
    const files = matchFolder.getFiles();
    const photos = [];
    while (files.hasNext()) {
      const f = files.next();
      photos.push({ id: f.getId(), url: 'https://lh3.googleusercontent.com/d/' + f.getId(), name: f.getName() });
    }
    return { ok: true, photos: photos };
  } catch (err) {
    return { ok: false, error: String(err) };
  }
}

function getOrCreateSubfolder(parent, name) {
  const safeName = String(name).trim();
  const existing = parent.getFoldersByName(safeName);
  if (existing.hasNext()) return existing.next();
  return parent.createFolder(safeName);
}

function formatInstaDate(dateStr, heureStr) {
  if (!dateStr) return '';
  const parts = String(dateStr).split('/'); // DD/MM/YYYY
  if (parts.length !== 3) return '';
  const d = new Date(parseInt(parts[2], 10), parseInt(parts[1], 10) - 1, parseInt(parts[0], 10));
  const jour = JOURS_FR[d.getDay()];
  return heureStr ? `${jour} ${heureStr}` : jour;
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
