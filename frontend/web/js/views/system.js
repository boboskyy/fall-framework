// views/system.js — infra, demoted into the bottom drawer.
import { api } from '../api.js';
import { getDatasets } from '../store.js';
import { shortName, family, dsLabel } from '../format.js';
import { qs, qsa, esc, spinner, healthBadge, toast } from '../components.js';
import { t } from '../i18n.js';

export async function render(root) {
  root.innerHTML = `<h2 class="sec-h">${esc(t('system_h'))}<span class="rule"></span></h2>
    <div id="sys-grid">${spinner('…')}</div>
    <h2 class="sec-h mt2">${esc(t('datasets_h'))}<span class="rule"></span></h2>
    <div id="sys-ds" class="grid auto"></div>`;

  async function loadDetectors() {
    const grid = qs('#sys-grid', root);
    try {
      const d = await api.detectors(true);
      const dets = (d.detectors || []).sort((a, b) => family(a.name).localeCompare(family(b.name)));
      grid.innerHTML = `<div class="grid auto">` + dets.map(x => `
        <div class="panel" data-det="${esc(x.name)}">
          <div class="row between">
            <div class="row" style="gap:.5rem">
              <span class="fam">${family(x.name)}</span>
              <strong class="mono">${esc(shortName(x.name))}</strong>
            </div>
            ${healthBadge(x.container_status)}
          </div>
          <div class="muted-note mt" style="margin-top:.5rem">
            ${esc(x.category || '')} · :${x.port} · ${x.requires_gpu ? 'gpu' : 'cpu'}${x.device ? ' (' + esc(x.device) + ')' : ''}
          </div>
          <div class="btn-row mt">
            <button class="btn sm" data-act="start">${esc(t('start_c'))}</button>
            <button class="btn sm ghost" data-act="stop">${esc(t('stop_c'))}</button>
            <button class="btn sm ghost" data-act="build">${esc(t('build_c'))}</button>
          </div>
        </div>`).join('') + `</div>`;

      qsa('[data-act]', grid).forEach(b => b.addEventListener('click', async () => {
        const name = b.closest('[data-det]').dataset.det;
        const act = b.dataset.act;
        b.disabled = true; b.textContent = '…';
        try {
          if (act === 'start') await api.startDetector(name);
          if (act === 'stop') await api.stopDetector(name);
          if (act === 'build') await api.buildDetector(name);
          toast(`${shortName(name)}: ${act} ok`, 'ok');
        } catch (e) { toast(`${shortName(name)}: ${e.message || e}`, 'err'); }
        loadDetectors();
      }));
    } catch (e) { grid.innerHTML = `<div class="empty">${esc(e.message || e)}</div>`; }
  }
  loadDetectors();

  try {
    const ds = await getDatasets();
    qs('#sys-ds', root).innerHTML = ds.map(d => {
      const st = d.statistics || {};
      return `<div class="panel">
        <strong class="mono">${esc(dsLabel(d.name))}</strong>
        <div class="muted-note mt" style="margin-top:.5rem">
          ${st.total_files ?? '?'} files · ${st.total_fall ?? '?'} fall / ${st.total_adl ?? '?'} adl · ${esc(d.input_type || '')}
        </div></div>`;
    }).join('') || '<div class="empty">no datasets</div>';
  } catch {}
}
