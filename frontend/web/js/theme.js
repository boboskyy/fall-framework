// theme.js — dark/light palette toggle (proj- style). Dark is the default;
// light is an opt-in, high-contrast palette for weak projectors. The choice is
// persisted in localStorage and applied via <html data-theme="…">. The initial
// attribute is set by a tiny inline script in index.html (before first paint) to
// avoid a flash of the wrong theme; this module keeps it in sync afterwards.
const KEY = 'fallfw-theme';
const THEMES = ['dark', 'light'];

function stored() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

// Default = dark (we deliberately ignore prefers-color-scheme: the user wants
// dark unless they explicitly switch).
let _theme = THEMES.includes(stored()) ? stored() : 'dark';
const _subs = new Set();

export function theme() { return _theme; }

export function setTheme(name) {
  if (!THEMES.includes(name)) return;
  _theme = name;
  document.documentElement.setAttribute('data-theme', name);
  try { localStorage.setItem(KEY, name); } catch {}
  _subs.forEach(fn => fn());
}

export function toggleTheme() { setTheme(_theme === 'dark' ? 'light' : 'dark'); }

export function onTheme(fn) { _subs.add(fn); return () => _subs.delete(fn); }

// Reconcile: make sure the live attribute matches our resolved value (the inline
// head script may not have run, e.g. when served oddly).
document.documentElement.setAttribute('data-theme', _theme);
