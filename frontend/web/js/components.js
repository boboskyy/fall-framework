// components.js — tiny DOM helpers shared by all views.
export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function spinner(label = '') {
  return `<span class="spinner"><span class="sp"></span>${esc(label)}</span>`;
}
export function empty(big, sub = '') {
  return `<div class="empty"><span class="big">${esc(big)}</span>${esc(sub)}</div>`;
}

let toastHost = null;
export function toast(msg, type = 'info', ms = 3200) {
  if (!toastHost) {
    toastHost = document.createElement('div');
    toastHost.className = 'toast-wrap';
    document.body.appendChild(toastHost);
  }
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  toastHost.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; setTimeout(() => el.remove(), 320); }, ms);
}

// health → badge class + label
export function healthBadge(status) {
  const map = {
    healthy: ['ok', 'healthy'], unhealthy: ['bad', 'unhealthy'], error: ['bad', 'error'],
    stopped: ['muted', 'stopped'], not_built: ['warn', 'not built'],
    not_downloaded: ['warn', 'not downloaded'], building: ['info', 'building'],
    downloading: ['info', 'downloading'], starting: ['info', 'starting'], unknown: ['muted', 'unknown'],
  };
  const [cls, lab] = map[status] || ['muted', status || 'unknown'];
  return `<span class="badge ${cls}"><span class="dotled"></span>${lab}</span>`;
}

export function download(filename, text, mime = 'text/csv') {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// serialize an inline <svg> to a downloadable PNG
export function svgToPng(svgEl, filename, scale = 2) {
  const xml = new XMLSerializer().serializeToString(svgEl);
  const vb = svgEl.viewBox.baseVal;
  const w = (vb && vb.width) || svgEl.clientWidth || 600;
  const h = (vb && vb.height) || svgEl.clientHeight || 360;
  const img = new Image();
  img.onload = () => {
    const c = document.createElement('canvas');
    c.width = w * scale; c.height = h * scale;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#1a1a1e'; ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, 0, c.width, c.height);
    c.toBlob(b => download(filename, b, 'image/png'));
  };
  img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(xml)));
}
