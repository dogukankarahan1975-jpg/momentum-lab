// Haltedauer je Position (vom Nutzer beim Kauf festgelegt) und Kalender-Erinnerungen (.ics).
// Alles bleibt auf dem iPhone: Erinnerungen laufen über die Kalender-App, nicht über einen Server.

export const HOLD_CHOICES = [
  ['', 'Bis zum Verkaufssignal der App'],
  ['3', '3 Monate'],
  ['6', '6 Monate'],
  ['12', '12 Monate'],
];
export const SELL_FEE = 1;

const pad = (n) => String(n).padStart(2, '0');
const eurTxt = (x) => `${x.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const dmy = (i) => `${i.slice(8, 10)}.${i.slice(5, 7)}.${i.slice(0, 4)}`;
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Erster Werktag (Mo–Fr) eines Monats = Screening-Tag. */
export function screeningDay(year, month0) {
  const d = new Date(year, month0, 1, 12);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  return d;
}

/** Ende der Haltedauer: erster Screening-Tag ab (Kaufdatum + n Monate − 7 Tage Toleranz). */
export function holdEnd(buyISO, months) {
  const b = new Date(`${buyISO}T12:00:00`);
  const target = new Date(b.getFullYear(), b.getMonth() + months, b.getDate() - 7, 12);
  let d = screeningDay(target.getFullYear(), target.getMonth());
  if (d < target) d = screeningDay(target.getFullYear(), target.getMonth() + 1);
  return iso(d);
}

export function nextScreeningDay(todayISO) {
  const t = new Date(`${todayISO}T12:00:00`);
  let d = screeningDay(t.getFullYear(), t.getMonth());
  if (iso(d) < todayISO) d = screeningDay(t.getFullYear(), t.getMonth() + 1);
  return iso(d);
}

/**
 * Status der Haltedauer einer offenen Position.
 * item: Ergebnis von computePosition (costOpen, mvEUR, firstOpen)
 */
export function holdStatus(pos, item, todayISO) {
  const months = Number(pos.holdMonths);
  if (!(months > 0) || !item?.firstOpen || !(item.qty > 0)) return null;
  const end = holdEnd(item.firstOpen, months);
  const net = Number.isFinite(item.mvEUR) ? item.mvEUR - SELL_FEE - item.costOpen : null;
  const days = Math.round((Date.parse(`${end}T12:00:00`) - Date.parse(`${todayISO}T12:00:00`)) / 864e5);
  const base = { months, end, days, net, breakEven: !!pos.holdBE, since: item.firstOpen };
  if (days > 0) return { ...base, state: 'laeuft', label: `Haltedauer bis ${dmy(end)}`, text: `Noch ${days} Tage. Am ${dmy(end)} ist der Verkaufstermin (Screening-Tag).` };
  if (net == null) return { ...base, state: 'pruefen', label: 'Haltedauer vorbei', text: 'Haltedauer vorbei. Kein aktueller Kurs vorhanden – bitte selbst prüfen.' };
  if (net >= 0) return { ...base, state: 'verkaufen', label: 'VERKAUFEN: Haltedauer vorbei', text: `Die ${months} Monate sind um und die Position ist nach Verkaufsgebühr im Plus (${eurTxt(net)}). Verkaufen und das Geld beim Screening neu verteilen.` };
  if (pos.holdBE) return { ...base, state: 'warten', label: 'HALTEN bis ±0', text: `Die ${months} Monate sind um, aber die Position liegt ${eurTxt(-net)} im Minus. Deine Regel: weiter halten, bis sie wieder bei ±0 ist.` };
  return { ...base, state: 'verkaufen', label: 'VERKAUFEN: Haltedauer vorbei', text: `Die ${months} Monate sind um. Die Position liegt ${eurTxt(-net)} im Minus. Deine Regel: trotzdem verkaufen.` };
}

// ------------------------------------------------------------------ Kalender (.ics)
const esc = (s) => String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
const dt = (isoDate, hh = 8) => `${isoDate.replace(/-/g, '')}T${pad(hh)}0000`;

export function buildICS(events) {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Momentum Lab//DE', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH'];
  for (const e of events) {
    lines.push('BEGIN:VEVENT', `UID:${e.uid}@momentum-lab`, `DTSTAMP:${stamp}`,
      `DTSTART;TZID=Europe/Berlin:${dt(e.date, e.hour ?? 8)}`, `DTEND;TZID=Europe/Berlin:${dt(e.date, (e.hour ?? 8) + 1)}`,
      `SUMMARY:${esc(e.title)}`, `DESCRIPTION:${esc(e.desc || '')}`);
    if (e.rrule) lines.push(`RRULE:${e.rrule}`);
    lines.push('BEGIN:VALARM', 'ACTION:DISPLAY', `DESCRIPTION:${esc(e.title)}`, 'TRIGGER:PT0M', 'END:VALARM', 'END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  return lines.join('\r\n');
}

/** Öffnet die Datei im Kalender (iPhone: „Hinzufügen“) – Teilen-Menü, sonst Download. */
export async function openICS(filename, text) {
  const file = new File([text], filename, { type: 'text/calendar' });
  if (navigator.canShare && navigator.canShare({ files: [file] })) {
    try { await navigator.share({ files: [file], title: filename }); return 'share'; } catch (e) { if (e?.name === 'AbortError') return 'abort'; }
  }
  const a = document.createElement('a');
  a.href = `data:text/calendar;charset=utf-8,${encodeURIComponent(text)}`;
  a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  return 'download';
}

export function holdEvents(items) {
  // gleiche Verkaufstermine zusammenfassen
  const by = new Map();
  for (const it of items) {
    const st = holdStatus(it.pos, it, '1900-01-01');
    if (!st) continue;
    if (!by.has(st.end)) by.set(st.end, []);
    by.get(st.end).push({ name: it.pos.name, be: !!it.pos.holdBE, months: st.months });
  }
  return [...by.entries()].map(([date, list]) => ({
    uid: `hold-${date}`, date, hour: 8,
    title: `Verkaufen: ${list.map((x) => x.name).join(', ')}`,
    desc: `Haltedauer vorbei für: ${list.map((x) => `${x.name} (${x.months} Monate${x.be ? ', im Minus warten bis ±0' : ''})`).join('; ')}. `
      + 'Öffne Momentum Lab → Depot: Dort steht je Aktie, ob verkaufen (im Plus) oder weiter halten bis ±0. Danach Screening starten und neu kaufen.',
  }));
}

export function screeningEvent() {
  return {
    uid: 'monthly-screening', date: nextScreeningDay(iso(new Date())), hour: 8,
    title: 'Momentum Lab: Monats-Screening',
    desc: 'Erster Werktag im Monat: App öffnen → Screening starten. Fällige Verkäufe umsetzen, dann mit dem Rechner die neuen Käufe aufteilen.',
    rrule: 'FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=1',
  };
}

/** Aufteilung für Neukäufe: Gutschrift + neues Geld auf n Aktien, je Kauf feste Gebühr. */
export function splitBuy(total, n, fee = 1) {
  if (!(n > 0) || !(total > 0)) return { each: 0, orderEach: 0, fees: 0 };
  const fees = n * fee;
  const orderEach = Math.max(0, (total - fees) / n);
  return { each: orderEach + fee, orderEach, fees };
}
