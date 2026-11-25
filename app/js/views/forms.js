// Eingabemasken (Bottom-Sheets): Transaktion, Sparplan, manueller Kurs, Position bearbeiten.
import { HOLD_CHOICES } from '../holding.js';
import { cachedScreen, loadScreen } from '../data.js';
import { replay, INTERVALS } from '../depot.js';
import { fmtDate, fmtNum, parseDec, todayISO, uid } from '../fmt.js';
import { reloadDepot, state, go } from '../state.js';
import { db } from '../store.js';
import { esc, html, openSheet, toast } from '../ui.js';

const CURRENCIES = ['EUR', 'USD', 'GBP', 'CHF', 'JPY', 'CAD', 'AUD', 'SEK', 'DKK', 'NOK', 'HKD', 'SGD', 'ILS', 'NZD'];
const TYPES = [['BUY', 'Kauf'], ['SELL', 'Verkauf'], ['DIV', 'Dividende'], ['SPLIT', 'Split']];

function rerender() { window.dispatchEvent(new HashChangeEvent('hashchange')); }

export async function openTxForm({ preset = {}, tx = null } = {}) {
  let screen = cachedScreen();
  if (!screen) { try { screen = await loadScreen(); } catch { screen = null; } }
  const fixedPos = tx ? state.positions.find((p) => p.id === tx.positionId)
    : preset.positionId ? state.positions.find((p) => p.id === preset.positionId) : null;
  let type = tx?.type || preset.type || 'BUY';
  let chosen = fixedPos ? null : (preset.symbol ? { symbol: preset.symbol, name: preset.name, currency: preset.currency, isin: preset.isin, exchange: preset.exchange } : null);
  const plans = fixedPos ? state.plans.filter((p) => p.positionId === fixedPos.id) : [];
  const v = (k, d = '') => (tx && tx[k] != null ? tx[k] : preset[k] != null ? preset[k] : d);
  const fmtIn = (x) => (x === '' || x == null ? '' : String(x).replace('.', ','));
  const title = tx ? 'Transaktion bearbeiten' : fixedPos ? fixedPos.name : 'Position erfassen';
  const body = String(html`
    ${fixedPos ? '' : html`<div id="pick">
      <label class="field"><span>Aktie suchen (Name, Ticker oder ISIN)</span><input id="q" type="search" autocomplete="off" placeholder="z. B. Siemens, NVDA, DE0007236101" value="${chosen ? chosen.name : ''}"></label>
      <div class="search-results" id="res" hidden></div>
      <details class="more" id="manual-d"><summary>Aktie ist nicht in der Liste</summary>
        <label class="field"><span>Name</span><input id="m-name" autocomplete="off"></label>
        <label class="field"><span>Yahoo-Symbol (optional, z. B. SAP.DE)</span><input id="m-sym" autocomplete="off" autocapitalize="characters"></label>
        <p class="xs muted">Ohne Symbol im Universum gibt es keine automatischen Kurse und Signale. Den Kurs kannst du dann manuell eintragen.</p>
      </details>
      <div id="chosen" class="note info" ${chosen ? '' : 'hidden'}><span class="ic">✓</span><div id="chosen-t">${chosen ? `${chosen.name} (${chosen.symbol})` : ''}</div></div>
    </div>`}
    <div class="seg" role="group" aria-label="Art">${TYPES.map(([k, l]) => html`<button type="button" data-type="${k}" aria-pressed="${k === type}" ${!fixedPos && k !== 'BUY' ? 'disabled' : ''}>${l}</button>`)}</div>
    <label class="field"><span>Datum</span><input id="date" type="date" value="${v('date', todayISO())}" max="${todayISO()}"></label>
    <div data-for="BUY SELL">
      <div class="grid2">
        <label class="field"><span>Stückzahl</span><input id="qty" inputmode="decimal" autocomplete="off" value="${fmtIn(v('qty'))}" placeholder="z. B. 2,5"></label>
        <label class="field"><span>Kurs je Aktie</span><input id="price" inputmode="decimal" autocomplete="off" value="${fmtIn(v('price'))}"></label>
      </div>
      <label class="field" data-for="BUY"><span>oder Gesamtbetrag (ohne Stückzahl)</span><input id="amount" inputmode="decimal" autocomplete="off" placeholder="z. B. 100 bei Sparplan" value="${fmtIn(preset.buyAmount ?? '')}"><div class="hint">Stückzahl = (Betrag − Gebühren) ÷ Kurs</div></label>
      <div class="grid2">
        <label class="field"><span>Währung</span><select id="cur">${CURRENCIES.map((c) => html`<option ${c === (v('currency', 'EUR')) ? 'selected' : ''}>${c}</option>`)}</select></label>
        <label class="field"><span>Gebühren</span><input id="fees" inputmode="decimal" autocomplete="off" value="${fmtIn(v('fees', ''))}" placeholder="0"></label>
      </div>
      <label class="field" id="fx-f" hidden><span id="fx-l">Wechselkurs</span><input id="fx" inputmode="decimal" autocomplete="off" value="${fmtIn(v('fx', ''))}"><div class="hint">Am besten aus der Abrechnung deiner Bank übernehmen.</div></label>
      ${plans.length ? html`<label class="field" data-for="BUY"><span>Sparplan</span><select id="plan"><option value="">kein Sparplan</option>${plans.map((p) => html`<option value="${p.id}" ${v('planId') === p.id ? 'selected' : ''}>${fmtNum(p.amount, 2)} € ${INTERVALS[p.interval] || ''}</option>`)}</select></label>` : ''}
    </div>
    <div data-for="DIV">
      <div class="grid2">
        <label class="field"><span>Gutschrift netto (€)</span><input id="div" inputmode="decimal" value="${fmtIn(v('amount', ''))}"></label>
        <label class="field"><span>Einbehaltene Steuer (€)</span><input id="divtax" inputmode="decimal" value="${fmtIn(v('tax', ''))}" placeholder="optional"></label>
      </div>
    </div>
    <div data-for="SPLIT">
      <label class="field"><span>Neue Aktien je alte Aktie</span><input id="ratio" inputmode="decimal" value="${fmtIn(v('ratio', ''))}" placeholder="4 bei 4:1, 0,1 bei 1:10"></label>
    </div>
    <div data-for="BUY">
      <label class="field"><span>Wie lange willst du halten?</span><select id="holdm">${HOLD_CHOICES.map(([k, l]) => html`<option value="${k}" ${String(fixedPos?.holdMonths ?? preset.holdMonths ?? '') === k ? 'selected' : ''}>${l}</option>`)}</select>
        <div class="hint">Bei 6 oder 12 Monaten zeigt die App am Verkaufstermin (erster Werktag des Monats nach Ablauf) „Verkaufen“. Erinnerung per Kalender möglich.</div></label>
      <label class="check" style="display:flex;gap:8px;align-items:center;margin:-4px 0 12px"><input type="checkbox" id="holdbe" ${fixedPos?.holdBE ?? preset.holdBE ?? true ? 'checked' : ''}><span class="small">Im Minus nicht verkaufen, sondern warten bis ±0</span></label>
    </div>
    <label class="field"><span>Notiz (optional)</span><input id="note" autocomplete="off" value="${v('note', '')}"></label>
    <p class="err-text" id="err" hidden></p>
    <div class="btn-row"><button class="btn primary block" id="save">Speichern</button></div>`);
  openSheet({
    title, body, onMount: (el, close) => {
      const $ = (s) => el.querySelector(s);
      const sync = () => {
        el.querySelectorAll('[data-for]').forEach((n) => { n.hidden = !n.dataset.for.split(' ').includes(type); });
        el.querySelectorAll('[data-type]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.type === type)));
        const cur = $('#cur')?.value;
        const fxf = $('#fx-f');
        if (fxf) {
          fxf.hidden = !(type === 'BUY' || type === 'SELL') || cur === 'EUR';
          $('#fx-l').textContent = `Wechselkurs: 1 EUR = ? ${cur}`;
          const rate = screen?.fx?.rates?.[cur];
          if (!fxf.hidden && !$('#fx').value && rate) $('#fx').value = String(rate).replace('.', ',');
        }
      };
      el.querySelectorAll('[data-type]').forEach((b) => { b.onclick = () => { type = b.dataset.type; sync(); }; });
      $('#cur') && ($('#cur').onchange = () => { $('#fx').value = ''; sync(); });
      sync();
      if (!fixedPos) {
        const q = $('#q'), res = $('#res');
        q.oninput = () => {
          const term = q.value.trim().toLowerCase();
          if (!screen || term.length < 2) { res.hidden = true; return; }
          const hits = screen.rows.filter((r) => `${r.name} ${r.symbol} ${r.isin || ''}`.toLowerCase().includes(term)).slice(0, 12);
          res.hidden = !hits.length;
          res.innerHTML = hits.map((r) => `<button type="button" data-s="${esc(r.symbol)}"><b>${esc(r.name)}</b><div class="xs muted">${esc(r.symbol)}, ${esc(r.country || '')}${r.isin ? `, ${esc(r.isin)}` : ''}</div></button>`).join('');
        };
        res.onclick = (e) => {
          const b = e.target.closest('[data-s]');
          if (!b) return;
          const r = screen.bySymbol.get(b.dataset.s);
          chosen = { symbol: r.symbol, name: r.name, currency: r.currency, isin: r.isin, exchange: r.exchange };
          q.value = r.name; res.hidden = true;
          $('#chosen').hidden = false; $('#chosen-t').textContent = `${r.name} (${r.symbol})`;
        };
      }
      $('#save').onclick = async () => {
        const err = $('#err');
        const fail = (m) => { err.textContent = m; err.hidden = false; };
        err.hidden = true;
        try {
          let pos = fixedPos;
          if (!pos) {
            const mName = $('#m-name').value.trim();
            const mSym = $('#m-sym').value.trim().toUpperCase();
            const target = chosen || (mName ? { symbol: mSym || `EIGEN-${uid().slice(0, 8)}`, name: mName, currency: 'EUR' } : null);
            if (!target) return fail('Bitte eine Aktie auswählen oder Namen eingeben.');
            pos = state.positions.find((p) => p.symbol === target.symbol);
            if (!pos) {
              pos = { id: uid(), symbol: target.symbol, name: target.name, isin: target.isin || '', exchange: target.exchange || '',
                currency: target.currency || 'EUR', note: '', manualPrice: null, createdAt: new Date().toISOString() };
              await db.put('positions', pos);
            }
          }
          const date = $('#date').value;
          if (!date) return fail('Bitte ein Datum angeben.');
          if (date > todayISO()) return fail('Das Datum liegt in der Zukunft.');
          const rec = { id: tx?.id || uid(), positionId: pos.id, type, date, note: $('#note').value.trim(), createdAt: tx?.createdAt || new Date().toISOString() };
          if (type === 'BUY' || type === 'SELL') {
            const price = parseDec($('#price').value);
            const fees = $('#fees').value.trim() ? parseDec($('#fees').value) : 0;
            let qty = parseDec($('#qty').value);
            const amount = parseDec($('#amount')?.value || '');
            if (!(price > 0)) return fail('Bitte einen gültigen Kurs eingeben.');
            if (!(fees >= 0)) return fail('Gebühren ungültig.');
            if (!(qty > 0) && type === 'BUY' && amount > fees) qty = (amount - fees) / price;
            if (!(qty > 0)) return fail('Bitte eine gültige Stückzahl (oder einen Betrag) eingeben.');
            const cur = $('#cur').value;
            const fx = cur === 'EUR' ? 1 : parseDec($('#fx').value);
            if (!(fx > 0)) return fail('Bitte den Wechselkurs angeben.');
            Object.assign(rec, { qty, price, fees, currency: cur, fx });
            const pid = $('#plan')?.value;
            if (pid) rec.planId = pid;
            if (type === 'SELL') {
              const others = state.txs.filter((t) => t.positionId === pos.id && t.id !== rec.id);
              const held = replay(others, date).qty;
              if (qty > held + 1e-9) return fail(`Am ${fmtDate(date)} waren nur ${fmtNum(held, 4)} Stück im Bestand.`);
            }
          } else if (type === 'DIV') {
            const amount = parseDec($('#div').value);
            if (!(amount > 0)) return fail('Bitte den Gutschriftsbetrag eingeben.');
            rec.amount = amount;
            rec.tax = $('#divtax').value.trim() ? parseDec($('#divtax').value) : null;
            rec.currency = 'EUR';
          } else if (type === 'SPLIT') {
            const ratio = parseDec($('#ratio').value);
            if (!(ratio > 0) || ratio === 1) return fail('Bitte ein gültiges Verhältnis eingeben (z. B. 4 oder 0,1).');
            rec.ratio = ratio;
          }
          await db.put('transactions', rec);
          if (type === 'BUY') {
            const hm = $('#holdm')?.value;
            pos.holdMonths = hm ? Number(hm) : null;
            pos.holdBE = !!$('#holdbe')?.checked;
            await db.put('positions', pos);
          }
          await reloadDepot();
          close();
          toast('Gespeichert');
          if (!fixedPos) go(`#/position/${encodeURIComponent(pos.id)}`); else rerender();
        } catch (e) { fail(e.message || String(e)); }
      };
    },
  });
}

export function openPlanForm(pos, plan = null) {
  let interval = plan?.interval || 'monthly';
  const body = String(html`
    <label class="field"><span>Sparrate (€)</span><input id="amt" inputmode="decimal" value="${plan ? String(plan.amount).replace('.', ',') : ''}" placeholder="z. B. 100"></label>
    <div class="seg" role="group" aria-label="Intervall">${Object.entries(INTERVALS).map(([k, l]) => html`<button type="button" data-i="${k}" aria-pressed="${k === interval}">${l}</button>`)}</div>
    <div class="grid2">
      <label class="field"><span>Start</span><input id="start" type="date" value="${plan?.start || todayISO()}"></label>
      <label class="field"><span>Ausführungstag (1–28)</span><input id="day" inputmode="numeric" value="${plan?.day || 1}"></label>
    </div>
    <label class="toggle"><span>Sparplan aktiv</span><input id="active" type="checkbox" ${plan?.active === false ? '' : 'checked'}></label>
    <p class="err-text" id="err" hidden></p>
    <div class="btn-row"><button class="btn primary" id="save">Speichern</button>${plan ? html`<button class="btn danger" id="del">Sparplan löschen</button>` : ''}</div>`);
  openSheet({
    title: plan ? 'Sparplan bearbeiten' : `Sparplan für ${pos.name}`, body, onMount: (el, close) => {
      el.querySelectorAll('[data-i]').forEach((b) => { b.onclick = () => { interval = b.dataset.i; el.querySelectorAll('[data-i]').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); }; });
      el.querySelector('#save').onclick = async () => {
        const amount = parseDec(el.querySelector('#amt').value);
        const day = Math.round(parseDec(el.querySelector('#day').value));
        const err = el.querySelector('#err');
        if (!(amount > 0)) { err.textContent = 'Bitte eine Sparrate eingeben.'; err.hidden = false; return; }
        if (!(day >= 1 && day <= 28)) { err.textContent = 'Ausführungstag muss zwischen 1 und 28 liegen.'; err.hidden = false; return; }
        const active = el.querySelector('#active').checked;
        const rec = { id: plan?.id || uid(), positionId: pos.id, amount, interval, day, start: el.querySelector('#start').value || todayISO(),
          active, stoppedAt: !active ? (plan?.stoppedAt || todayISO()) : null, createdAt: plan?.createdAt || new Date().toISOString() };
        await db.put('plans', rec);
        await reloadDepot();
        close(); toast('Sparplan gespeichert'); rerender();
      };
      const del = el.querySelector('#del');
      if (del) del.onclick = async () => {
        if (!confirm('Sparplan löschen? Bereits erfasste Käufe bleiben erhalten.')) return;
        await db.del('plans', plan.id);
        await reloadDepot();
        close(); toast('Sparplan gelöscht'); rerender();
      };
    },
  });
}

export function openManualPrice(pos) {
  const m = pos.manualPrice || {};
  const body = String(html`<p class="small muted">Nur nötig, wenn der Datenlauf für diese Aktie keine Kurse liefert. Automatische Kurse haben Vorrang.</p>
    <div class="grid2"><label class="field"><span>Kurs</span><input id="p" inputmode="decimal" value="${m.price != null ? String(m.price).replace('.', ',') : ''}"></label>
    <label class="field"><span>Währung</span><select id="c">${CURRENCIES.map((c) => html`<option ${c === (m.currency || 'EUR') ? 'selected' : ''}>${c}</option>`)}</select></label></div>
    <label class="field"><span>Kursdatum</span><input id="d" type="date" value="${m.date || todayISO()}"></label>
    <div class="btn-row"><button class="btn primary" id="save">Speichern</button>${pos.manualPrice ? html`<button class="btn" id="rm">Manuellen Kurs entfernen</button>` : ''}</div>`);
  openSheet({ title: 'Kurs manuell eintragen', body, onMount: (el, close) => {
    el.querySelector('#save').onclick = async () => {
      const price = parseDec(el.querySelector('#p').value);
      if (!(price > 0)) { toast('Bitte einen gültigen Kurs eingeben'); return; }
      pos.manualPrice = { price, currency: el.querySelector('#c').value, date: el.querySelector('#d').value || todayISO() };
      await db.put('positions', pos); await reloadDepot(); close(); rerender();
    };
    const rm = el.querySelector('#rm');
    if (rm) rm.onclick = async () => { pos.manualPrice = null; await db.put('positions', pos); await reloadDepot(); close(); rerender(); };
  } });
}

export function openPositionEdit(pos) {
  const body = String(html`<label class="field"><span>Name</span><input id="n" value="${pos.name}"></label>
    <label class="field"><span>Symbol (Yahoo)</span><input id="s" value="${pos.symbol}" autocapitalize="characters"></label>
    <div class="grid2"><label class="field"><span>ISIN</span><input id="i" value="${pos.isin || ''}" autocapitalize="characters"></label>
    <label class="field"><span>Börse</span><input id="b" value="${pos.exchange || ''}"></label></div>
    <label class="field"><span>Haltedauer</span><select id="hm">${HOLD_CHOICES.map(([k, l]) => html`<option value="${k}" ${String(pos.holdMonths ?? '') === k ? 'selected' : ''}>${l}</option>`)}</select></label>
    <label class="check" style="display:flex;gap:8px;align-items:center;margin:-4px 0 12px"><input type="checkbox" id="be" ${pos.holdBE ? 'checked' : ''}><span class="small">Im Minus nicht verkaufen, sondern warten bis ±0</span></label>
    <label class="field"><span>Notizen</span><textarea id="t">${pos.note || ''}</textarea></label>
    <div class="btn-row"><button class="btn primary" id="save">Speichern</button></div>`);
  openSheet({ title: 'Position bearbeiten', body, onMount: (el, close) => {
    el.querySelector('#save').onclick = async () => {
      Object.assign(pos, { name: el.querySelector('#n').value.trim() || pos.name, symbol: el.querySelector('#s').value.trim().toUpperCase() || pos.symbol,
        isin: el.querySelector('#i').value.trim().toUpperCase(), exchange: el.querySelector('#b').value.trim(), note: el.querySelector('#t').value,
        holdMonths: el.querySelector('#hm').value ? Number(el.querySelector('#hm').value) : null, holdBE: el.querySelector('#be').checked });
      await db.put('positions', pos); await reloadDepot(); close(); toast('Gespeichert'); rerender();
    };
  } });
}
