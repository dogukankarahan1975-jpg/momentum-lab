// Portfolio Intelligence: Signale für gehaltene Aktien und Sparpläne.
// Regeln (Methodik v1.0, vor dem Backtest festgelegt):
//  - Verkaufsbedingung H: Rang außerhalb Halteband (Top 20 %) ODER 12-1-Momentum <= 0 ODER kein gültiger Score.
//  - VERKAUF nur, wenn H an zwei Monatsenden in Folge gilt (Vormonat + jetzt) oder "schwer" (unter Median / Momentum <= -10 %).
//  - Einmaliges H => VERKAUF PRÜFEN (Bestätigung am nächsten Monatsende).
//  - Datenprobleme => VERKAUF PRÜFEN (nie automatisch VERKAUF).
//  - Ein schlechterer Rang allein ist kein Verkaufsgrund, solange die Aktie im Halteband bleibt.
//  - Neues Geld (Sparplan) folgt dem aktuellen Ranking (Top 5 %), bestehende Positionen den Halteregeln.

export const DEFAULT_PARAMS = { hold_max_pct: 0.2, sell_immediate_pct: 0.5, savings_max_pct: 0.05, confirm_months: 2 };

const pctTxt = (p) => (Number.isFinite(p) ? `${(p * 100).toFixed(p < 0.1 ? 1 : 0).replace('.', ',')} %` : '–');
const retTxt = (r) => (Number.isFinite(r) ? `${r > 0 ? '+' : ''}${(r * 100).toFixed(1).replace('.', ',')} %` : '–');

/*
 input: {
   row: Zeile aus screen.json (oder null), fresh: {ok, abort, level}, globalStatus: 'ok'|'warnung'|'fehler',
   inCandidates: bool, topPick: symbol|null, weight: Anteil am Depot (0..1)|null, maxWeight,
   plan: {active, amount}|null, bestAlternative: {symbol, name}|null, params
 }
*/
export function evaluateHolding(input) {
  const p = { ...DEFAULT_PARAMS, ...(input.params || {}) };
  const row = input.row;
  const criteria = [];
  const reasons = [];
  const crit = (label, okv, value = '', info = false) => criteria.push({ label, ok: okv, value, info });
  let signal, urgency, next;

  const dataUsable = !!(row && Number.isFinite(row.last_close));
  const notCurrent = !input.fresh?.ok || input.globalStatus === 'fehler';

  if (!dataUsable) {
    signal = 'KEINE BEWERTUNG';
    urgency = 'unbekannt';
    reasons.push('Für diese Aktie liefert der Datenlauf keine Kurse. Sie ist nicht im Universum oder nicht abrufbar.');
    next = 'Symbol prüfen oder Aktie in die Beobachtungsliste (config/watchlist.txt) aufnehmen.';
    crit('Kursdaten vorhanden', false);
    return finish();
  }
  if (notCurrent) {
    signal = 'KEINE BEWERTUNG';
    urgency = 'unbekannt';
    reasons.push(input.globalStatus === 'fehler'
      ? 'Der letzte Datenlauf ist fehlgeschlagen. Ohne geprüfte Daten gibt es keine Empfehlung.'
      : `Der Datenstand ist ${input.fresh?.label || 'nicht aktuell'}. Ohne aktuelle Daten gibt es keine Empfehlung.`);
    next = 'Neues Screening starten, sobald aktuelle Daten vorliegen.';
    crit('Datenstand aktuell', false, input.fresh?.label || '');
    return finish();
  }

  const scoreValid = Number.isFinite(row.Z);
  const inBand = scoreValid && row.pct <= p.hold_max_pct;
  const momPos = Number.isFinite(row.m12) && row.m12 > 0;
  crit('Kurse aktuell und plausibel', !!row.data_ok, row.data_ok ? '' : (row.reasons || []).map((c) => (input.reasonLabel ? input.reasonLabel(c) : c)).join(', '));
  crit('Gültiger Momentum-Score', scoreValid, scoreValid ? `Score ${row.Z.toFixed(2).replace('.', ',')}` : '');
  crit(`Rang im Halteband (beste ${Math.round(p.hold_max_pct * 100)} %)`, inBand, scoreValid ? `Top ${pctTxt(row.pct)}` : '–');
  crit('12-Monats-Momentum (ohne letzten Monat) positiv', momPos, retTxt(row.m12));
  crit('6-Monats-Momentum (ohne letzten Monat) positiv', Number.isFinite(row.m6) && row.m6 > 0, retTxt(row.m6), true);
  crit('Kurs über 200-Tage-Linie', row.above_ma200 === true, row.above_ma200 == null ? 'n. v.' : retTxt(row.dist_ma200), true);
  crit('Kurs mit Zweitquelle gegengeprüft', row.verified === true ? true : row.verified === false ? false : null,
    row.verified == null ? 'nicht verfügbar' : '', true);

  const H = !!row.H;
  const severe = !!row.severe;
  const Hprev = row.H_prev === true;

  if (!row.data_ok) {
    signal = 'VERKAUF PRÜFEN';
    urgency = 'mittel';
    reasons.push('Die Kursdaten dieser Aktie sind auffällig. Das kann ein Datenfehler oder ein echtes Ereignis sein, zum Beispiel eine Übernahme, ein Delisting oder eine Handelsaussetzung. Bitte prüfe das selbst.');
    next = 'Unternehmensmeldungen prüfen. Bei einem Datenfehler bleibt die Position bestehen.';
  } else if (H && (Hprev || severe)) {
    signal = 'VERKAUF';
    urgency = 'hoch';
    if (severe) reasons.push(row.pct > p.sell_immediate_pct
      ? `Die Aktie ist unter den Median des Universums gefallen (Top ${pctTxt(row.pct)}). Das Momentum ist klar verloren.`
      : `Das 12-Monats-Momentum ist deutlich negativ (${retTxt(row.m12)}).`);
    else reasons.push('Die Verkaufsbedingung ist am zweiten Monatsende in Folge erfüllt.');
    if (!inBand && scoreValid) reasons.push(`Rang außerhalb des Haltebands (Top ${pctTxt(row.pct)} statt beste ${Math.round(p.hold_max_pct * 100)} %).`);
    if (!momPos) reasons.push(`12-Monats-Momentum nicht mehr positiv (${retTxt(row.m12)}).`);
    next = 'Verkauf umsetzen. Den Erlös in den aktuellen Top Pick oder die Top-10-Kandidaten umschichten.';
  } else if (H) {
    signal = 'VERKAUF PRÜFEN';
    urgency = 'mittel';
    if (!scoreValid) reasons.push('Für die Aktie gibt es derzeit keinen gültigen Momentum-Score.');
    if (scoreValid && !inBand) reasons.push(`Die Aktie liegt außerhalb des Haltebands (Top ${pctTxt(row.pct)}).`);
    if (!momPos) reasons.push(`Das 12-Monats-Momentum ist nicht mehr positiv (${retTxt(row.m12)}).`);
    reasons.push('Die Bedingung ist zum ersten Mal erfüllt. Damit Kurzfristschwankungen keinen Verkauf auslösen, wartet die Regel auf eine Bestätigung am nächsten Monatsende.');
    next = 'Ist die Bedingung am nächsten Monatsende weiter erfüllt, folgt VERKAUF. Sonst bleibt es bei HALTEN.';
  } else {
    const roomOk = !(Number.isFinite(input.weight) && input.weight >= (input.maxWeight ?? 0.2));
    crit('Unter den aktuellen Top 10', !!input.inCandidates, input.inCandidates ? '' : 'nein', true);
    if (Number.isFinite(input.weight)) crit(`Depotanteil unter ${Math.round((input.maxWeight ?? 0.2) * 100)} %`, roomOk, pctTxt(input.weight), true);
    if (input.inCandidates && roomOk && row.above_ma200 !== false) {
      signal = 'NACHKAUFEN';
      urgency = 'niedrig';
      reasons.push('Die Aktie gehört zu den aktuellen Top 10 und erfüllt alle Kriterien. Ein Zukauf ist mit der Strategie vereinbar.');
      next = 'Optional zukaufen. Die Halteregeln gelten unverändert.';
    } else {
      signal = 'HALTEN';
      urgency = 'niedrig';
      reasons.push(`Die Aktie liegt im Halteband (Top ${pctTxt(row.pct)}) und hat positives 12-Monats-Momentum. Ein schlechterer Rang allein ist kein Verkaufsgrund.`);
      if (input.inCandidates && !roomOk) reasons.push('Kein Zukauf: Die Position ist bereits groß im Verhältnis zum Depot (Klumpenrisiko).');
      if (row.above_ma200 === false) reasons.push('Hinweis: Der Kurs liegt unter der 200-Tage-Linie. Das ist kein Verkaufssignal, aber ein Warnzeichen für einen Trendbruch.');
      if (row.pct > p.hold_max_pct * 0.75) reasons.push('Hinweis: Die Aktie nähert sich der Grenze des Haltebands.');
      next = `Verkauf erst, wenn Rang schlechter als beste ${Math.round(p.hold_max_pct * 100)} % oder 12-Monats-Momentum <= 0 an zwei Monatsenden in Folge.`;
    }
  }
  if (input.fresh?.level === 'leicht veraltet') reasons.push(`Achtung: Datenstand ${input.fresh.label}.`);
  if (input.globalStatus === 'warnung') reasons.push('Der letzte Datenlauf hat Warnungen gemeldet (siehe Einstellungen > Datenquellen).');
  return finish();

  function finish() {
    const plan = input.plan && input.plan.active !== false ? evaluatePlan(input, signal, p) : null;
    return { signal, urgency, reasons, criteria, next, plan };
  }
}

function evaluatePlan(input, posSignal, p) {
  const row = input.row;
  const alt = input.bestAlternative;
  const altText = alt ? `Wechselkandidat: ${alt.name} (${alt.symbol}).` : 'Derzeit gibt es keinen Kandidaten, der alle Kriterien erfüllt. Neue Raten besser pausieren.';
  if (posSignal === 'KEINE BEWERTUNG') {
    return { signal: 'KEINE BEWERTUNG', urgency: 'unbekannt', reasons: ['Ohne aktuelle, geprüfte Daten gibt es keine Sparplan-Empfehlung.'], switchTo: null };
  }
  if (posSignal === 'VERKAUF' || posSignal === 'VERKAUF PRÜFEN') {
    return { signal: 'SPARPLAN STOPPEN', urgency: posSignal === 'VERKAUF' ? 'hoch' : 'mittel',
      reasons: ['Keine neuen Raten in eine Position mit Verkaufs- oder Prüfsignal.', altText], switchTo: alt };
  }
  const ok = Number.isFinite(row?.pct) && row.pct <= p.savings_max_pct && row.m12 > 0 && row.above_ma200 !== false;
  if (ok) {
    return { signal: 'SPARPLAN FORTSETZEN', urgency: 'niedrig',
      reasons: [`Die Aktie gehört weiterhin zu den besten ${Math.round(p.savings_max_pct * 100)} % des Universums (Top ${pctTxt(row.pct)}).`], switchTo: null };
  }
  const why = row.above_ma200 === false ? 'Der Kurs liegt unter der 200-Tage-Linie.' : `Die Aktie gehört nicht mehr zu den besten ${Math.round(p.savings_max_pct * 100)} % (aktuell Top ${pctTxt(row.pct)}).`;
  return { signal: 'SPARPLAN STOPPEN', urgency: 'mittel',
    reasons: [why, 'Die bestehende Position wird weiter gehalten. Nur neue Raten sollten in einen stärkeren Titel fließen.', altText], switchTo: alt };
}

export function urgencyRank(u) { return { hoch: 0, mittel: 1, niedrig: 2, unbekannt: 3 }[u] ?? 4; }
