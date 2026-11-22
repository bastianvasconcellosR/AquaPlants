/* Cliente HTTP de la API. Mismo origen, así que no hay problemas de CORS. */
const API = (() => {
  const BASE = '/api/v1';
  let token = null;
  try { token = sessionStorage.getItem('aq_token'); } catch (e) { /* almacenamiento bloqueado */ }
  let onSesionExpirada = () => {};

  function setToken(t) {
    token = t;
    try { t ? sessionStorage.setItem('aq_token', t) : sessionStorage.removeItem('aq_token'); } catch (e) {}
  }

  async function req(metodo, ruta, cuerpo, opciones = {}) {
    const h = {};
    if (token) h['Authorization'] = 'Bearer ' + token;
    if (cuerpo !== undefined) h['Content-Type'] = 'application/json';
    let r;
    try {
      r = await fetch(BASE + ruta, { method: metodo, headers: h, body: cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined });
    } catch (e) {
      const err = new Error('Sin conexión con el servidor. Reintente en unos segundos.');
      err.red = true;
      throw err;
    }
    if (opciones.blob && r.ok) return r.blob();
    let datos = null;
    try { datos = await r.json(); } catch (e) {}
    if (!r.ok) {
      if (r.status === 401 && token && !ruta.startsWith('/auth/login')) onSesionExpirada();
      let msg = (datos && datos.error) || ('Error ' + r.status);
      if (datos && datos.detalles) msg += ': ' + datos.detalles.map(d => d.campo + ' – ' + d.mensaje).join('; ');
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    return datos;
  }

  return {
    get: (r) => req('GET', r), post: (r, b) => req('POST', r, b), put: (r, b) => req('PUT', r, b),
    patch: (r, b) => req('PATCH', r, b), del: (r) => req('DELETE', r), blob: (r) => req('GET', r, undefined, { blob: true }),
    setToken, hayToken: () => !!token, alExpirar: (f) => { onSesionExpirada = f; },
  };
})();
