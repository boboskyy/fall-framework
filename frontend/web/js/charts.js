// charts.js — hand-rolled SVG / CSS charts in the proj- aesthetic
// (square, dotted axes, diagonal-hatch fills). All return HTML strings.
import { dec, pct } from './format.js';
import { esc } from './components.js';

/* striped horizontal bar (the signature element). value/max in [0,1] usually */
export function stripedBar(value, { max = 1, best = false, cls = '', height = '' } = {}) {
  const w = Math.max(0, Math.min(100, (value / max) * 100));
  return `<div class="bar ${best ? 'best' : ''} ${height}"><div class="fill ${cls}" style="width:${w}%"></div></div>`;
}

const PALETTE = ['#ffffff', '#3b82f6', '#98c379', '#d19a66', '#b392f0', '#e06c75',
                 '#56b6c2', '#c678dd', '#61afef', '#e5c07b', '#7f848e'];
export const colorFor = (i) => PALETTE[i % PALETTE.length];

/* multi-line chart. series = [{name,color,best,points:[[x,y]…]}]
   xDomain/yDomain = [min,max]. */
export function lineChart(series, {
  xDomain = [1, 30], yDomain = [0, 1], w = 560, h = 240,
  xLabel = '', yLabel = '', xTicks = 6, yTicks = 5, marker = null,
} = {}) {
  const pad = { l: 34, r: 12, t: 10, b: 26 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const sx = (x) => pad.l + (x - xDomain[0]) / (xDomain[1] - xDomain[0] || 1) * iw;
  const sy = (y) => pad.t + ih - (y - yDomain[0]) / (yDomain[1] - yDomain[0] || 1) * ih;
  let g = '';
  // grid + y ticks
  for (let i = 0; i <= yTicks; i++) {
    const v = yDomain[0] + (yDomain[1] - yDomain[0]) * i / yTicks;
    const y = sy(v);
    g += `<line class="axis" x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}"/>`;
    g += `<text x="${pad.l - 5}" y="${y + 3}" text-anchor="end">${dec(v, 1)}</text>`;
  }
  for (let i = 0; i <= xTicks; i++) {
    const v = Math.round(xDomain[0] + (xDomain[1] - xDomain[0]) * i / xTicks);
    const x = sx(v);
    g += `<text x="${x}" y="${h - pad.b + 14}" text-anchor="middle">${v}</text>`;
  }
  // marker (vertical line, e.g. current threshold)
  if (marker != null) {
    const x = sx(marker);
    g += `<line class="axis-solid" x1="${x}" y1="${pad.t}" x2="${x}" y2="${pad.t + ih}" stroke="#3b82f6" stroke-dasharray="3 2"/>`;
  }
  // lines
  for (const s of series) {
    if (s.hidden) continue;
    const pts = s.points.map(([x, y]) => `${sx(x).toFixed(1)},${sy(y).toFixed(1)}`).join(' ');
    g += `<polyline class="ln ${s.best ? 'best' : ''}" points="${pts}" stroke="${s.color}"/>`;
  }
  if (yLabel) g += `<text x="4" y="${pad.t + 8}" fill="#8a8a93">${esc(yLabel)}</text>`;
  if (xLabel) g += `<text x="${w - pad.r}" y="${h - 2}" text-anchor="end" fill="#8a8a93">${esc(xLabel)}</text>`;
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">${g}</svg>`;
}

/* scatter. points = [{x,y,label,best,bad}]. ideal corner highlighted. */
export function scatter(points, {
  xDomain = [0, 1], yDomain = [0, 1], w = 480, h = 320,
  xLabel = 'FPR', yLabel = 'recall', ideal = [0, 1], iso = true,
} = {}) {
  const pad = { l: 36, r: 14, t: 14, b: 30 };
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const sx = (x) => pad.l + (x - xDomain[0]) / (xDomain[1] - xDomain[0] || 1) * iw;
  const sy = (y) => pad.t + ih - (y - yDomain[0]) / (yDomain[1] - yDomain[0] || 1) * ih;
  let g = '';
  for (let i = 0; i <= 5; i++) {
    const v = i / 5;
    g += `<line class="axis" x1="${sx(v)}" y1="${pad.t}" x2="${sx(v)}" y2="${pad.t + ih}"/>`;
    g += `<line class="axis" x1="${pad.l}" y1="${sy(v)}" x2="${w - pad.r}" y2="${sy(v)}"/>`;
    g += `<text x="${sx(v)}" y="${h - pad.b + 13}" text-anchor="middle">${dec(v, 1)}</text>`;
    g += `<text x="${pad.l - 5}" y="${sy(v) + 3}" text-anchor="end">${dec(v, 1)}</text>`;
  }
  // ideal corner
  g += `<rect x="${sx(ideal[0]) - 4}" y="${sy(ideal[1]) - 4}" width="8" height="8" fill="none" stroke="#98c379" stroke-dasharray="2 2"/>`;
  g += `<text x="${sx(ideal[0]) + 7}" y="${sy(ideal[1]) + 3}" fill="#98c379">ideal</text>`;
  for (const p of points) {
    const cls = p.best ? 'best' : (p.bad ? 'bad' : '');
    g += `<rect class="pt ${cls}" x="${sx(p.x) - 3}" y="${sy(p.y) - 3}" width="6" height="6"/>`;
    g += `<text class="lab" x="${sx(p.x) + 6}" y="${sy(p.y) + 3}">${esc(p.label)}</text>`;
  }
  g += `<text x="${w - pad.r}" y="${h - 4}" text-anchor="end" fill="#8a8a93">${esc(xLabel)} →</text>`;
  g += `<text x="6" y="${pad.t + 6}" fill="#8a8a93">↑ ${esc(yLabel)}</text>`;
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">${g}</svg>`;
}

/* histogram from counts[] (already binned). highlight bins by predicate. */
export function histogram(counts, { labels = null, hl = () => false } = {}) {
  const max = Math.max(1, ...counts);
  const bars = counts.map((c, i) =>
    `<div class="b ${hl(i) ? 'hl' : ''}" style="height:${(c / max) * 100}%" title="${c}"></div>`).join('');
  const xs = (labels || counts.map((_, i) => i)).map(l => `<span>${esc(l)}</span>`).join('');
  return `<div class="hist">${bars}</div><div class="hist-x">${xs}</div>`;
}

/* diverging κ color: positive → white intensity, negative → blue intensity */
export function kappaColor(v) {
  if (v == null) return 'var(--panel)';
  if (v >= 0) return `rgba(255,255,255,${(0.06 + v * 0.5).toFixed(3)})`;
  return `rgba(59,130,246,${(0.08 + Math.abs(v) * 0.45).toFixed(3)})`;
}
