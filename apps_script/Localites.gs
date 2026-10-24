/**
 * Dependent dropdowns for the location columns: the Ville list of a row depends on its Région, and the Localité list
 * on its Ville (see README, "Location dropdowns").
 *
 * Install once, in the Sheet: Extensions > Apps Script, paste this file (replacing any earlier version) and save.
 * Then run `refreshAll` once (Run button, function list) and accept the authorisation Google asks for, then run
 * `installTrigger` once and accept again. Nothing is sent anywhere.
 *
 * The hidden "Lieux" tab (written by `make format-sheet`) has one row per localité: column A the Région, B the Ville,
 * C the Localité. When a Région or a Ville is edited (onEdit, a simple trigger), the Ville and Localité cells of that
 * row get a dropdown with only the villes of the Région and only the localités of the Ville (66 at most); other
 * values can still be typed (a warning, not a refusal). The lists appear about 3 seconds after the choice. With no
 * Région, a Ville that exists in only one région still gets its localités. Edits made by the sync do not fire
 * onEdit, so installTrigger adds a nightly refresh of every row. In our test onOpen (the "Lieux" menu and a refresh
 * when the Sheet opens) did not fire by itself, so do not rely on it.
 */
var DATA_TAB = 'Contacts';
var LIEUX_TAB = 'Lieux';
var FIRST_ROW = 2;
var LAST_ROW = 2000;

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Lieux')
      .addItem('Actualiser les listes', 'refreshAll')
      .addToUi();
  refreshAll();
}

function onEdit(e) {
  var range = e.range;
  var sheet = range.getSheet();
  if (sheet.getName() !== DATA_TAB) return;
  var col = columns_(sheet);
  if (!col['Région'] || !col['Ville'] || !col['Localité']) return;
  if (range.getColumn() > col['Ville'] || range.getLastColumn() < col['Région']) return;   // neither Région nor Ville
  var first = Math.max(range.getRow(), FIRST_ROW);
  var last = Math.min(range.getLastRow(), LAST_ROW);
  if (last >= first) refresh_(sheet, col, first, last);
}

function refreshAll() {
  var sheet = SpreadsheetApp.getActive().getSheetByName(DATA_TAB);
  if (!sheet) return;
  var col = columns_(sheet);
  if (!col['Région'] || !col['Ville'] || !col['Localité']) return;
  refresh_(sheet, col, FIRST_ROW, Math.min(sheet.getMaxRows(), LAST_ROW));
}

function refresh_(sheet, col, first, last) {
  var n = last - first + 1;
  var regions = sheet.getRange(first, col['Région'], n, 1).getValues();
  var villes = sheet.getRange(first, col['Ville'], n, 1).getValues();
  var tree = tree_();
  var built = {};                                    // one rule per list, reused by every row that needs it
  var villeRules = [], localiteRules = [];
  for (var i = 0; i < n; i++) {
    var region = String(regions[i][0]).trim();
    var ville = String(villes[i][0]).trim();
    villeRules.push([rule_(built, 'v|' + region, tree.villes[region])]);
    var key = region + '|' + ville;
    if (!tree.localites.hasOwnProperty(key)) key = (region === '') ? tree.onlyRegion[ville] : null;   // unique ville
    localiteRules.push([rule_(built, 'l|' + key, key ? tree.localites[key] : null)]);
  }
  sheet.getRange(first, col['Ville'], n, 1).setDataValidations(villeRules);
  sheet.getRange(first, col['Localité'], n, 1).setDataValidations(localiteRules);
}

function rule_(built, id, items) {
  if (!items || !items.length) return null;          // unknown or empty parent: free text
  if (!built[id]) {
    built[id] = SpreadsheetApp.newDataValidation().requireValueInList(items, true).setAllowInvalid(true).build();
  }
  return built[id];
}

function tree_() {
  var tab = SpreadsheetApp.getActive().getSheetByName(LIEUX_TAB);
  var tree = {villes: {}, localites: {}, onlyRegion: {}};
  if (!tab || tab.getLastRow() < 2) return tree;
  var seen = {};
  tab.getRange(2, 1, tab.getLastRow() - 1, 3).getValues().forEach(function (r) {
    var region = String(r[0]), ville = String(r[1]), localite = String(r[2]);
    if (!region || !ville || !localite) return;
    var key = region + '|' + ville;
    if (!tree.villes.hasOwnProperty(region)) tree.villes[region] = [];
    if (!tree.localites.hasOwnProperty(key)) {
      tree.localites[key] = [];
      tree.villes[region].push(ville);
      tree.onlyRegion[ville] = tree.onlyRegion.hasOwnProperty(ville) ? null : key;   // null: the name is in 2 régions
    }
    tree.localites[key].push(localite);
  });
  return tree;
}

function columns_(sheet) {
  var header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var col = {};
  header.forEach(function (h, i) { col[String(h).trim()] = i + 1; });
  return col;
}

function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'refreshAll') ScriptApp.deleteTrigger(t);   // run twice, still one trigger
  });
  ScriptApp.newTrigger('refreshAll').timeBased().everyDays(1).atHour(3).create();   // after the nightly sync
}
