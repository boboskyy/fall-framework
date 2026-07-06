// router.js — minimal hash router with query params (#/path?a=b).
const routes = [];
let notFound = null;

export function route(path, handler) { routes.push({ path, handler }); }
export function setNotFound(fn) { notFound = fn; }

export function parse() {
  const h = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = h.split('?');
  const params = Object.fromEntries(new URLSearchParams(qs || ''));
  return { path: path || '/', params, hash: h };
}

export function go(path) { location.hash = path; }
export function href(path, params) {
  const q = params ? '?' + new URLSearchParams(params).toString() : '';
  return '#' + path + q;
}

let _onChange = () => {};
export function onChange(fn) { _onChange = fn; }

export function start() {
  const dispatch = () => {
    const { path, params } = parse();
    const r = routes.find(r => r.path === path);
    _onChange(path);
    if (r) r.handler(params);
    else if (notFound) notFound(path);
  };
  window.addEventListener('hashchange', dispatch);
  dispatch();
}
