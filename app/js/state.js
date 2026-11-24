// Gemeinsamer App-Zustand (Depot aus IndexedDB, zuletzt geladene Daten).
import { db, loadSettings } from './store.js';

export const state = {
  settings: null, positions: [], txs: [], plans: [], lastScreening: null, booted: false,
};

export async function reloadDepot() {
  const [positions, txs, plans] = await Promise.all([db.all('positions'), db.all('transactions'), db.all('plans')]);
  state.positions = positions.sort((a, b) => String(a.name).localeCompare(String(b.name), 'de'));
  state.txs = txs;
  state.plans = plans;
  return state;
}
export async function reloadSettings() {
  state.settings = await loadSettings();
  return state.settings;
}
export async function screenings() {
  const all = await db.all('screenings');
  return all.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
}
export async function latestScreening() {
  const all = await screenings();
  state.lastScreening = all[0] || null;
  return state.lastScreening;
}
export function go(hash) {
  if (location.hash === hash) window.dispatchEvent(new HashChangeEvent('hashchange'));
  else location.hash = hash;
}
