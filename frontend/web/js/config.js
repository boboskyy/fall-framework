// config.js — runtime config from the gateway (preview/read-only flag).
import { api } from './api.js';

let _cfg = { preview: false };
export const isPreview = () => _cfg.preview;

export async function loadConfig() {
  try { _cfg = await api.config(); } catch { _cfg = { preview: false }; }
  document.body.classList.toggle('preview', !!_cfg.preview);
  return _cfg;
}
