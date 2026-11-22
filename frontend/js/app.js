/* AquaPlants | AquaBrain – interfaz web. JavaScript puro, sin dependencias.
   Toda cadena que viene del servidor se escapa con esc() antes de insertarse en el HTML (anti-XSS). */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const VARIABLES = { ph: 'pH', temperatura_agua: 'Temperatura del agua', caudal: 'Caudal', conductividad_ec: 'Conductividad (EC)', humedad_ambiente: 'Humedad ambiente' };
const nombreVar = (v) => VARIABLES[v] || v;

let usuario = null, vista = null, timerEstado = null, ultimoEstado = null;
const POLL_MS = 30000;

/* ---------- utilidades de interfaz ---------- */
function toast(msg, error = false) {
  const t = $('#toast'); t.textContent = msg; t.className = error ? 'error' : ''; t.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 4500);
}
const fmtFecha = (iso) => iso ? new Date(iso).toLocaleString('es-CL', { dateStyle: 'short', timeStyle: 'medium' }) : '—';
function hace(iso) {
  if (!iso) return 'nunca';
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (s < 60) return `hace ${s} s`;
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return `hace ${Math.round(s / 86400)} d`;
}
const cargando = () => '<div class="estado">Cargando…</div>';
const vacio = (t) => `<div class="estado">${esc(t)}</div>`;
const errorBox = (m) => `<div class="msg error" role="alert">${esc(m)}</div>`;
const badge = (txt, clase) => `<span class="badge ${clase}">${esc(txt)}</span>`;

/* Diálogo de formulario genérico → Promise<objeto|null> */
function formulario(titulo, campos, valores = {}, textoOk = 'Guardar') {
  const dlg = $('#dlg'), cont = $('#dlg-campos'), err = $('#dlg-error');
  $('#dlg-titulo').textContent = titulo; $('#dlg-ok').textContent = textoOk; err.hidden = true;
  cont.innerHTML = campos.map(c => {
    const v = valores[c.n] ?? c.def ?? '';
    const id = 'f-' + c.n, req = c.req ? ' required' : '';
    let ctl;
    if (c.tipo === 'select') ctl = `<select id="${id}"${req}>${c.opciones.map(o => `<option value="${esc(o.v)}"${String(o.v) === String(v) ? ' selected' : ''}>${esc(o.t)}</option>`).join('')}</select>`;
    else if (c.tipo === 'checkbox') return `<label style="flex-direction:row;align-items:center;gap:8px"><input id="${id}" type="checkbox"${(v === '' ? true : v) ? ' checked' : ''}>${esc(c.etq)}</label>`;
    else if (c.tipo === 'multi') return `<fieldset><legend class="hint">${esc(c.etq)}</legend>${c.opciones.map(o => `<label style="flex-direction:row;align-items:center;gap:8px"><input type="checkbox" name="${id}" value="${esc(o.v)}" checked>${esc(o.t)}</label>`).join('')}</fieldset>`;
    else if (c.tipo === 'textarea') ctl = `<textarea id="${id}" rows="3" maxlength="${c.max || 500}"${req}>${esc(v)}</textarea>`;
    else ctl = `<input id="${id}" type="${c.tipo || 'text'}" value="${esc(v)}"${req}${c.step ? ` step="${c.step}"` : ''}${c.ph ? ` placeholder="${esc(c.ph)}"` : ''}>`;
    return `<label>${esc(c.etq)}${c.req ? ' *' : ''}${ctl}${c.ayuda ? `<span class="hint">${esc(c.ayuda)}</span>` : ''}</label>`;
  }).join('');
  return new Promise(resolve => {
    const form = $('#dlg-form');
    const cerrar = (r) => { form.onsubmit = null; $('#dlg-cancel').onclick = null; dlg.close(); resolve(r); };
    $('#dlg-cancel').onclick = () => cerrar(null);
    dlg.oncancel = () => cerrar(null);
    form.onsubmit = (ev) => {
      ev.preventDefault();
      const out = {};
      for (const c of campos) {
        const id = 'f-' + c.n;
        if (c.tipo === 'checkbox') out[c.n] = $('#' + id).checked;
        else if (c.tipo === 'multi') out[c.n] = [...document.getElementsByName(id)].filter(i => i.checked).map(i => i.value);
        else {
          let x = $('#' + id).value.trim();
          if (c.req && x === '') { err.textContent = `El campo «${c.etq}» es obligatorio.`; err.hidden = false; return; }
          if (['number'].includes(c.tipo) || c.num) x = x === '' ? null : Number(x);
          if (x === '' && !c.req) x = null;
          out[c.n] = x;
        }
      }
      cerrar(out);
    };
    if (!dlg.open) dlg.showModal();
  });
}

function dialogoClave(key, aviso) {
  const dlg = $('#dlg'); $('#dlg-titulo').textContent = 'API Key del dispositivo'; $('#dlg-ok').textContent = 'La guardé';
  $('#dlg-campos').innerHTML = `<div class="msg info">${esc(aviso)}</div><code class="key">${esc(key)}</code>`;
  $('#dlg-error').hidden = true;
  return new Promise(res => {
    $('#dlg-cancel').onclick = () => { dlg.close(); res(); };
    $('#dlg-form').onsubmit = (e) => { e.preventDefault(); dlg.close(); res(); };
    dlg.showModal();
  });
}

/* ---------- sesión ---------- */
async function iniciar() {
  API.alExpirar(() => { cerrarSesion('Su sesión expiró. Inicie sesión nuevamente.'); });
  if (API.hayToken()) {
    try { usuario = await API.get('/auth/me'); entrar(); return; } catch (e) { API.setToken(null); }
  }
  $('#vista-login').hidden = false;
}

$('#form-login').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const err = $('#l-error'); err.hidden = true;
  const email = $('#l-email').value.trim(), clave = $('#l-clave').value;
  if (!email || !clave) { err.textContent = 'Ingrese correo y contraseña.'; err.hidden = false; return; }
  const btn = ev.submitter; btn.disabled = true;
  try {
    const r = await API.post('/auth/login', { email, clave });
    API.setToken(r.token); usuario = r.usuario; $('#l-clave').value = ''; entrar();
  } catch (e) { err.textContent = e.message; err.hidden = false; }
  finally { btn.disabled = false; }
});

function entrar() {
  $('#vista-login').hidden = true; $('#app').hidden = false;
  $('#usuario-info').textContent = `${usuario.nombre} · ${usuario.rol}`;
  const items = [['estado', 'Estado actual'], ['alertas', 'Alertas'], ['historico', 'Históricos'], ['bitacora', 'Bitácora']];
  if (['Administrador', 'Supervisor'].includes(usuario.rol)) items.push(['informe', 'Informe de gestión']);
  if (usuario.rol === 'Administrador') items.push(['admin', 'Administración']);
  $('#nav').innerHTML = items.map(([k, t]) => `<button data-v="${k}">${t}</button>`).join('');
  irA('estado');
}
function cerrarSesion(msg) {
  clearInterval(timerEstado); API.setToken(null); usuario = null;
  $('#app').hidden = true; $('#vista-login').hidden = false;
  const err = $('#l-error'); if (msg) { err.textContent = msg; err.hidden = false; } else err.hidden = true;
}
$('#btn-salir').addEventListener('click', () => cerrarSesion());
$('#nav').addEventListener('click', (e) => { const b = e.target.closest('button[data-v]'); if (b) irA(b.dataset.v); });

function irA(v) {
  vista = v; clearInterval(timerEstado);
  document.querySelectorAll('#nav button').forEach(b => { b.dataset.v === v ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current'); });
  ({ estado: vEstado, alertas: vAlertas, historico: vHistorico, bitacora: vBitacora, informe: vInforme, admin: vAdmin })[v]();
}

/* ================= CU02 Estado actual ================= */
async function vEstado() {
  const m = $('#contenido');
  m.innerHTML = `<h1>Estado actual</h1><p class="sub">Última lectura de cada sensor. Se actualiza solo cada 30 segundos.</p><div id="aviso"></div><div id="kpis"></div><div id="devs">${cargando()}</div>`;
  const pintar = (est, fallo) => {
    ultimoEstado = est;
    $('#aviso').innerHTML = fallo ? `<div class="msg error" role="alert">Sin conexión con el servidor. Se muestran los últimos datos recibidos (${esc(fmtFecha(est.generado_en))}). Reintentando…</div>` : '';
    const enLinea = est.dispositivos.filter(d => d.conexion === 'en línea').length;
    $('#kpis').innerHTML = `<div class="grid g3" style="margin-bottom:14px">
      <div class="card kpi" style="margin:0"><span>Dispositivos en línea</span><b>${enLinea} / ${est.dispositivos.length}</b></div>
      <div class="card kpi" style="margin:0"><span>Alertas pendientes</span><b style="color:${est.alertas_pendientes ? 'var(--bad)' : 'inherit'}">${est.alertas_pendientes}</b></div>
      <div class="card kpi" style="margin:0"><span>Alertas en proceso</span><b>${est.alertas_en_proceso}</b></div></div>`;
    $('#devs').innerHTML = est.dispositivos.length ? est.dispositivos.map(d => `
      <div class="card"><div class="dev-head"><div><strong>${esc(d.nombre)}</strong> <span class="hint">${esc(d.codigo)} · ${esc(d.sistema)}</span></div>
        <div>${d.conexion === 'en línea' ? badge('En línea', 'b-ok') : badge('Sin conexión', 'b-bad')} <span class="hint">última comunicación ${esc(hace(d.ultima_comunicacion))}</span></div></div>
        <div class="table-wrap"><table><thead><tr><th>Variable</th><th>Valor</th><th>Rango permitido</th><th>Condición</th><th>Medido</th></tr></thead><tbody>
        ${d.sensores.map(s => `<tr><td>${esc(nombreVar(s.variable))}</td><td class="sensor-val">${s.valor ?? '—'} <span class="hint">${esc(s.unidad)}</span></td>
          <td>${s.minimo ?? '—'} a ${s.maximo ?? '—'}</td>
          <td>${s.condicion === 'normal' ? badge('Normal', 'b-ok') : s.condicion === 'fuera de rango' ? badge('Fuera de rango', 'b-bad') : badge('Sin datos', 'b-off')}</td>
          <td class="hint">${esc(hace(s.marca_tiempo))}</td></tr>`).join('') || '<tr><td colspan="5" class="hint">Sin sensores registrados</td></tr>'}
        </tbody></table></div></div>`).join('') : vacio('Aún no hay dispositivos registrados.');
  };
  const cargar = async () => {
    try { pintar(await API.get('/dashboard/estado'), false); }
    catch (e) {
      if (e.red && ultimoEstado) pintar(ultimoEstado, true);
      else if (vista === 'estado') $('#devs').innerHTML = errorBox(e.message);
    }
  };
  await cargar();
  timerEstado = setInterval(() => { if (vista === 'estado') cargar(); }, POLL_MS);
}

/* ================= CU03 / CU04 Alertas ================= */
async function vAlertas(filtro = '') {
  const m = $('#contenido');
  m.innerHTML = `<h1>Alertas</h1><p class="sub">Desviaciones de los parámetros del cultivo y caídas de conexión.</p>
    <div class="row"><label>Estado<select id="f-est"><option value="">Todas</option><option>Pendiente</option><option>En proceso</option><option>Resuelta</option></select></label></div>
    <div class="card" id="lista">${cargando()}</div>`;
  $('#f-est').value = filtro;
  $('#f-est').addEventListener('change', (e) => vAlertas(e.target.value));
  try {
    const as = await API.get('/alertas' + (filtro ? '?estado=' + encodeURIComponent(filtro) : ''));
    $('#lista').innerHTML = as.length ? `<div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Severidad</th><th>Dispositivo</th><th>Detalle</th><th>Estado</th><th>Causa / solución</th><th></th></tr></thead><tbody>
      ${as.map(a => `<tr class="sev-${esc(a.severidad)}"><td>${esc(fmtFecha(a.creada_en))}</td><td>${badge(a.severidad, a.severidad === 'Crítica' ? 'b-bad' : 'b-warn')}</td>
      <td>${esc(a.dispositivo)}</td><td>${esc(a.mensaje)}</td>
      <td>${badge(a.estado, a.estado === 'Resuelta' ? 'b-ok' : a.estado === 'Pendiente' ? 'b-bad' : 'b-warn')}</td><td>${esc(a.causa || '—')}</td>
      <td style="white-space:nowrap">${a.estado === 'Pendiente' ? `<button class="btn sec sm" data-a="proc" data-id="${a.id}">Tomar</button> ` : ''}${a.estado !== 'Resuelta' ? `<button class="btn sm" data-a="res" data-id="${a.id}">Resolver</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div>` : vacio('No hay alertas para este filtro.');
  } catch (e) { $('#lista').innerHTML = errorBox(e.message); }
}
$('#contenido').addEventListener('click', async (ev) => {
  const b = ev.target.closest('button[data-a]'); if (!b || vista !== 'alertas') return;
  const id = b.dataset.id;
  try {
    if (b.dataset.a === 'proc') await API.patch('/alertas/' + id, { estado: 'En proceso' });
    else {
      const d = await formulario('Resolver alerta', [{ n: 'causa', etq: 'Causa o solución aplicada', tipo: 'textarea', req: true, max: 255 }], {}, 'Resolver');
      if (!d) return;
      await API.patch('/alertas/' + id, { estado: 'Resuelta', causa: d.causa });
    }
    toast('Alerta actualizada'); vAlertas($('#f-est').value);
  } catch (e) { toast(e.message, true); vAlertas($('#f-est').value); }
});

/* ================= CU05 Histórico / CU12 CSV ================= */
async function vHistorico() {
  const m = $('#contenido');
  m.innerHTML = `<h1>Histórico y tendencias</h1><p class="sub">Evolución de una variable en un período.</p><div id="h-body">${cargando()}</div>`;
  let est;
  try { est = await API.get('/dashboard/estado'); } catch (e) { $('#h-body').innerHTML = errorBox(e.message); return; }
  const sensores = est.dispositivos.flatMap(d => d.sensores.map(s => ({ ...s, disp: d.codigo })));
  if (!sensores.length) { $('#h-body').innerHTML = vacio('No hay sensores registrados.'); return; }
  const puedeExportar = ['Administrador', 'Supervisor'].includes(usuario.rol);
  $('#h-body').innerHTML = `<div class="card"><div class="row">
    <label>Sensor<select id="h-sen">${sensores.map(s => `<option value="${s.id}">${esc(s.disp)} · ${esc(nombreVar(s.variable))}</option>`).join('')}</select></label>
    <label>Período<select id="h-per"><option value="24h">Últimas 24 horas</option><option value="7d">Últimos 7 días</option><option value="30d">Últimos 30 días</option><option value="x">Personalizado</option></select></label>
    <label class="pers" hidden>Desde<input type="date" id="h-d"></label><label class="pers" hidden>Hasta<input type="date" id="h-h"></label>
    <button class="btn" id="h-go">Consultar</button>${puedeExportar ? '<button class="btn sec" id="h-csv">Exportar CSV</button>' : ''}</div>
    <div id="h-msg"></div><canvas class="chart" id="h-cv" aria-label="Gráfico de tendencia"></canvas><div id="h-stats" class="grid g3" style="margin-top:10px"></div></div>`;
  const rango = () => {
    const p = $('#h-per').value, ahora = new Date();
    if (p === 'x') return { desde: $('#h-d').value, hasta: $('#h-h').value };
    const ms = { '24h': 864e5, '7d': 7 * 864e5, '30d': 30 * 864e5 }[p];
    return { desde: new Date(ahora - ms).toISOString().slice(0, 19) + 'Z', hasta: ahora.toISOString().slice(0, 19) + 'Z' };
  };
  const qs = () => { const r = rango(); const q = new URLSearchParams({ id_sensor: $('#h-sen').value }); if (r.desde) q.set('desde', r.desde); if (r.hasta) q.set('hasta', r.hasta); return q; };
  $('#h-per').addEventListener('change', () => document.querySelectorAll('.pers').forEach(l => l.hidden = $('#h-per').value !== 'x'));
  const consultar = async () => {
    $('#h-msg').innerHTML = '';
    try {
      const r = await API.get('/historico?' + qs());
      const s = sensores.find(x => String(x.id) === $('#h-sen').value);
      dibujarLinea($('#h-cv'), r.puntos, { minimo: s.minimo, maximo: s.maximo });
      $('#h-stats').innerHTML = [['Mediciones', r.total], ['Mínimo', r.minimo ?? '—'], ['Máximo', r.maximo ?? '—'], ['Promedio', r.promedio ?? '—']]
        .map(([k, v]) => `<div class="card kpi" style="margin:0"><span>${k}</span><b>${esc(v)}</b></div>`).join('');
      if (!r.total) $('#h-msg').innerHTML = '<div class="msg info">No hay mediciones en este período.</div>';
    } catch (e) { $('#h-msg').innerHTML = errorBox(e.message); }
  };
  $('#h-go').addEventListener('click', consultar);
  if (puedeExportar) $('#h-csv').addEventListener('click', async () => {
    try {
      const blob = await API.blob('/historico/export.csv?' + qs());
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'historico_aquaplants.csv'; a.click(); URL.revokeObjectURL(a.href);
      toast('CSV descargado');
    } catch (e) { toast(e.message, true); }
  });
  window.onresize = () => { if (vista === 'historico') consultar(); };
  consultar();
}

/* ================= Informe de gestión ================= */
async function vInforme() {
  const m = $('#contenido');
  m.innerHTML = `<h1>Informe de gestión</h1><p class="sub">Resumen del período: operación, calidad de los datos, alertas y desempeño por dispositivo.</p>
    <div class="card noimp"><div class="row"><label>Período<select id="i-per"><option value="24h">Últimas 24 horas</option><option value="7d">Últimos 7 días</option><option value="30d">Últimos 30 días</option></select></label>
    <button class="btn" id="i-go">Generar informe</button><button class="btn sec" id="i-imp">Imprimir / guardar PDF</button></div></div><div id="i-body">${cargando()}</div>`;
  const generar = async () => {
    const ms = { '24h': 864e5, '7d': 7 * 864e5, '30d': 30 * 864e5 }[$('#i-per').value], ahora = new Date();
    const q = new URLSearchParams({ desde: new Date(ahora - ms).toISOString().slice(0, 19) + 'Z', hasta: ahora.toISOString().slice(0, 19) + 'Z' });
    $('#i-body').innerHTML = cargando();
    try {
      const r = await API.get('/informes/gestion?' + q), x = r.resumen;
      const kpi = (k, v, sub = '') => `<div class="card kpi" style="margin:0"><span>${esc(k)}</span><b>${esc(v)}</b>${sub ? `<small>${esc(sub)}</small>` : ''}</div>`;
      $('#i-body').innerHTML = `<div class="card"><p class="sub" style="margin-top:0">Período: ${esc(fmtFecha(r.desde))} a ${esc(fmtFecha(r.hasta))} · Generado por ${esc(r.generado_por)} el ${esc(fmtFecha(r.generado_en))}</p>
        <h2>1. Resumen ejecutivo</h2><div class="grid g3">
        ${kpi('Dispositivos en línea', x.dispositivos_en_linea + ' / ' + x.dispositivos_activos, x.sensores_activos + ' sensores activos')}
        ${kpi('Mediciones recibidas', x.mediciones)}
        ${kpi('Fuera de rango', x.pct_fuera_de_rango + ' %', x.mediciones_fuera_de_rango + ' mediciones')}
        ${kpi('Alertas del período', x.alertas_periodo, x.alertas_criticas + ' críticas · ' + x.alertas_por_umbral + ' por umbral · ' + x.alertas_desconexion + ' por desconexión')}
        ${kpi('Alertas abiertas ahora', x.alertas_abiertas_ahora)}
        ${kpi('Tiempo medio de resolución', x.tiempo_medio_resolucion_min === null ? '—' : x.tiempo_medio_resolucion_min + ' min', x.alertas_resueltas + ' resueltas')}</div>
        <h2>2. Variables monitoreadas</h2>${r.por_variable.length ? `<div class="table-wrap"><table><thead><tr><th>Variable</th><th>Mediciones</th><th>Mínimo</th><th>Promedio</th><th>Máximo</th><th>Umbral</th><th>Fuera de rango</th></tr></thead><tbody>
        ${r.por_variable.map(v => `<tr><td>${esc(nombreVar(v.variable))}</td><td>${esc(v.mediciones)}</td><td>${esc(v.minimo)}</td><td>${esc(v.promedio)}</td><td>${esc(v.maximo)}</td><td>${v.umbral_min === null ? '—' : esc(v.umbral_min + ' – ' + v.umbral_max)}</td><td>${esc(v.fuera_de_rango + ' (' + v.pct_fuera + ' %)')}</td></tr>`).join('')}</tbody></table></div>` : vacio('Sin mediciones en el período.')}
        <h2>3. Desempeño por dispositivo</h2><div class="table-wrap"><table><thead><tr><th>Dispositivo</th><th>Instalación</th><th>Mediciones</th><th>Última comunicación</th></tr></thead><tbody>
        ${r.dispositivos.map(d => `<tr><td>${esc(d.codigo)} · ${esc(d.nombre)}</td><td>${esc(d.sistema)}</td><td>${esc((r.por_dispositivo.find(p => p.dispositivo === d.codigo) || {}).mediciones ?? 0)}</td><td>${esc(fmtFecha(d.ultima_comunicacion))}</td></tr>`).join('')}</tbody></table></div>
        <h2>4. Alertas del período</h2>${r.alertas.length ? `<div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Dispositivo</th><th>Severidad</th><th>Detalle</th><th>Estado</th><th>Causa</th></tr></thead><tbody>
        ${r.alertas.map(a => `<tr><td>${esc(fmtFecha(a.creada_en))}</td><td>${esc(a.dispositivo)}</td><td>${esc(a.severidad)}</td><td>${esc(a.mensaje)}</td><td>${esc(a.estado)}</td><td>${esc(a.causa ?? '—')}</td></tr>`).join('')}</tbody></table></div>` : vacio('Sin alertas en el período.')}
        <p class="sub">Registros de bitácora agrícola en el período: ${esc(x.registros_bitacora_agricola)}.</p></div>`;
    } catch (e) { $('#i-body').innerHTML = errorBox(e.message); }
  };
  $('#i-go').addEventListener('click', generar);
  $('#i-imp').addEventListener('click', () => window.print());
  generar();
}

/* ================= CU11 Bitácora ================= */
async function vBitacora(cat = 'agricola') {
  const m = $('#contenido'), esEnc = usuario.rol === 'Encargado', esAdm = usuario.rol === 'Administrador';
  m.innerHTML = `<h1>Bitácora</h1><p class="sub">${cat === 'agricola' ? 'Intervenciones realizadas sobre los cultivos.' : 'Registro de auditoría del sistema (solo Administrador).'}</p>
    ${esAdm ? `<div class="subtabs"><button data-c="agricola" aria-current="${cat === 'agricola'}">Agrícola</button><button data-c="auditoria" aria-current="${cat === 'auditoria'}">Auditoría</button></div>` : ''}
    ${esEnc && cat === 'agricola' ? '<div class="row"><button class="btn" id="b-nuevo">Registrar intervención</button></div>' : ''}
    <div class="card" id="b-lista">${cargando()}</div>`;
  m.querySelectorAll('.subtabs button').forEach(b => b.addEventListener('click', () => vBitacora(b.dataset.c)));
  if ($('#b-nuevo')) $('#b-nuevo').addEventListener('click', async () => {
    try {
      const cultivos = (await API.get('/cultivos')).filter(c => c.activo);
      const d = await formulario('Registrar intervención', [
        { n: 'id_cultivo', etq: 'Cultivo', tipo: 'select', opciones: cultivos.map(c => ({ v: c.id, t: c.nombre })), req: true },
        { n: 'accion', etq: 'Acción (siembra, cosecha, nutrientes, mantención…)', req: true },
        { n: 'detalle', etq: 'Detalle', tipo: 'textarea' }]);
      if (!d) return;
      d.id_cultivo = Number(d.id_cultivo);
      await API.post('/bitacora', d); toast('Registro guardado'); vBitacora('agricola');
    } catch (e) { toast(e.message, true); }
  });
  try {
    const f = await API.get('/bitacora?categoria=' + cat);
    $('#b-lista').innerHTML = f.length ? `<div class="table-wrap"><table><thead><tr><th>Fecha</th><th>Usuario</th>${cat === 'agricola' ? '<th>Cultivo</th>' : ''}<th>Acción</th><th>Detalle</th></tr></thead><tbody>
      ${f.map(x => `<tr><td>${esc(fmtFecha(x.creado_en))}</td><td>${esc(x.usuario || 'sistema')}</td>${cat === 'agricola' ? `<td>${esc(x.cultivo || '—')}</td>` : ''}<td>${esc(x.accion)}</td><td>${esc(x.detalle || '')}</td></tr>`).join('')}</tbody></table></div>` : vacio('Sin registros todavía.');
  } catch (e) { $('#b-lista').innerHTML = errorBox(e.message); }
}

/* ================= CU06 / CU07 / CU08 / CU13 Administración ================= */
const ENT = {
  usuarios: { titulo: 'Usuarios', ruta: '/usuarios', cols: [['nombre', 'Nombre'], ['email', 'Correo'], ['rol', 'Rol'], ['activo', 'Activo']] },
  sistemas: { titulo: 'Sistemas', ruta: '/sistemas', cols: [['nombre', 'Nombre'], ['ubicacion', 'Ubicación'], ['activo', 'Activo']] },
  cultivos: { titulo: 'Cultivos', ruta: '/cultivos', cols: [['nombre', 'Nombre'], ['especie', 'Especie'], ['fecha_inicio', 'Inicio'], ['activo', 'Activo']] },
  dispositivos: { titulo: 'Dispositivos', ruta: '/dispositivos', cols: [['codigo', 'Código'], ['nombre', 'Nombre'], ['ultima_comunicacion', 'Última comunicación'], ['activo', 'Activo']] },
  sensores: { titulo: 'Sensores', ruta: '/sensores', cols: [['id_dispositivo', 'Dispositivo'], ['variable', 'Variable'], ['unidad', 'Unidad'], ['activo', 'Activo']] },
  umbrales: { titulo: 'Umbrales', ruta: '/umbrales', cols: [['id_sistema', 'Sistema'], ['variable', 'Variable'], ['minimo', 'Mínimo'], ['maximo', 'Máximo']], sinBorrar: true },
  respaldos: { titulo: 'Respaldos', ruta: '/respaldos', cols: [['creado_en', 'Fecha'], ['tipo', 'Tipo'], ['archivo', 'Archivo'], ['tamano', 'Tamaño (B)'], ['estado', 'Estado']], solo: true },
};
let adminTab = 'usuarios', adminDatos = {};

async function vAdmin() {
  const m = $('#contenido');
  m.innerHTML = `<h1>Administración</h1><p class="sub">Gestión de usuarios, instalaciones, dispositivos, umbrales y respaldos.</p>
    <div class="subtabs" id="a-tabs">${Object.entries(ENT).map(([k, e]) => `<button data-t="${k}" aria-current="${k === adminTab}">${e.titulo}</button>`).join('')}</div>
    <div class="card" id="a-body">${cargando()}</div>`;
  $('#a-tabs').addEventListener('click', (e) => { const b = e.target.closest('button[data-t]'); if (b) { adminTab = b.dataset.t; vAdmin(); } });
  await adminTabla();
}

async function adminTabla() {
  const ent = ENT[adminTab], body = $('#a-body');
  try {
    const [filas, sis, disp] = await Promise.all([API.get(ent.ruta), API.get('/sistemas'), API.get('/dispositivos')]);
    adminDatos = { filas, sis, disp };
    const mapa = { id_sistema: Object.fromEntries(sis.map(s => [s.id, s.nombre])), id_dispositivo: Object.fromEntries(disp.map(d => [d.id, d.codigo])) };
    const celda = (f, k) => {
      let v = f[k];
      if (k === 'activo') return v ? badge('Sí', 'b-ok') : badge('No', 'b-off');
      if (k === 'creado_en' || k === 'ultima_comunicacion') return esc(fmtFecha(v));
      if (k === 'estado') return badge(v, v === 'Completo' ? 'b-ok' : 'b-bad');
      if (mapa[k]) v = mapa[k][v] ?? v;
      return esc(v ?? '—');
    };
    body.innerHTML = `<div class="row">${ent.solo ? '<button class="btn" data-x="resp">Crear respaldo ahora</button>' : '<button class="btn" data-x="nuevo">Nuevo</button>'}</div>
      ${filas.length ? `<div class="table-wrap"><table><thead><tr>${ent.cols.map(c => `<th>${c[1]}</th>`).join('')}${ent.solo ? '' : '<th></th>'}</tr></thead><tbody>
      ${filas.map(f => `<tr>${ent.cols.map(c => `<td>${celda(f, c[0])}</td>`).join('')}${ent.solo ? '' : `<td style="white-space:nowrap"><button class="btn sec sm" data-x="edit" data-id="${f.id}">Editar</button>
        ${!ent.sinBorrar && f.activo ? ` <button class="btn sec sm" data-x="del" data-id="${f.id}">Eliminar</button>` : ''}${adminTab === 'dispositivos' ? ` <button class="btn sec sm" data-x="key" data-id="${f.id}">Regenerar clave</button>` : ''}</td>`}</tr>`).join('')}
      </tbody></table></div>` : vacio('Sin registros.')}`;
  } catch (e) { body.innerHTML = errorBox(e.message); }
}

function camposDe(tab, edit) {
  const { sis, disp } = adminDatos;
  const optSis = sis.map(s => ({ v: s.id, t: s.nombre })), optDisp = disp.map(d => ({ v: d.id, t: d.codigo }));
  const optVar = Object.entries(VARIABLES).map(([v, t]) => ({ v, t }));
  return {
    usuarios: [{ n: 'nombre', etq: 'Nombre', req: true }, { n: 'email', etq: 'Correo', tipo: 'email', req: true },
      { n: 'clave', etq: 'Contraseña', tipo: 'password', req: !edit, ayuda: edit ? 'Déjela vacía para no cambiarla. ' : 'Mínimo 10 caracteres, con letras y números.' },
      { n: 'rol', etq: 'Rol', tipo: 'select', opciones: ['Administrador', 'Supervisor', 'Encargado'].map(r => ({ v: r, t: r })) }, { n: 'activo', etq: 'Activo', tipo: 'checkbox' }],
    sistemas: [{ n: 'nombre', etq: 'Nombre', req: true }, { n: 'ubicacion', etq: 'Ubicación' }, { n: 'activo', etq: 'Activo', tipo: 'checkbox' }],
    cultivos: [{ n: 'id_sistema', etq: 'Sistema', tipo: 'select', opciones: optSis, req: true }, { n: 'nombre', etq: 'Nombre', req: true }, { n: 'especie', etq: 'Especie' },
      { n: 'fecha_inicio', etq: 'Fecha de inicio', tipo: 'date' }, { n: 'activo', etq: 'Activo', tipo: 'checkbox' }],
    dispositivos: [{ n: 'id_sistema', etq: 'Sistema', tipo: 'select', opciones: optSis, req: true }, { n: 'codigo', etq: 'Código (único)', req: true, ph: 'AB-003' }, { n: 'nombre', etq: 'Nombre', req: true },
      { n: 'tipo', etq: 'Tipo', def: 'controlador' }, ...(edit ? [] : [{ n: 'variables', etq: 'Sensores a registrar', tipo: 'multi', opciones: optVar }]), { n: 'activo', etq: 'Activo', tipo: 'checkbox' }],
    sensores: [{ n: 'id_dispositivo', etq: 'Dispositivo', tipo: 'select', opciones: optDisp, req: true }, { n: 'variable', etq: 'Variable', tipo: 'select', opciones: optVar }, { n: 'activo', etq: 'Activo', tipo: 'checkbox' }],
    umbrales: [{ n: 'id_sistema', etq: 'Sistema', tipo: 'select', opciones: optSis, req: true }, { n: 'variable', etq: 'Variable', tipo: 'select', opciones: optVar },
      { n: 'minimo', etq: 'Mínimo', tipo: 'number', step: 'any', req: true }, { n: 'maximo', etq: 'Máximo', tipo: 'number', step: 'any', req: true }],
  }[tab];
}

$('#contenido').addEventListener('click', async (ev) => {
  const b = ev.target.closest('button[data-x]'); if (!b || vista !== 'admin') return;
  const ent = ENT[adminTab], id = b.dataset.id, fila = adminDatos.filas.find(f => String(f.id) === id);
  try {
    if (b.dataset.x === 'resp') {
      b.disabled = true; const r = await API.post('/respaldos'); toast('Respaldo ' + r.estado.toLowerCase()); return adminTabla();
    }
    if (b.dataset.x === 'del') {
      if (!confirm('¿Eliminar este registro? Es un borrado lógico: deja de usarse pero se conserva el historial. Podrá reactivarlo editándolo.')) return;
      await API.del(ent.ruta + '/' + id); toast('Registro eliminado (borrado lógico)'); return adminTabla();
    }
    if (b.dataset.x === 'key') {
      if (!confirm('La clave actual dejará de funcionar. ¿Regenerar?')) return;
      const r = await API.post(`/dispositivos/${id}/regenerar-clave`); await dialogoClave(r.api_key, r.aviso); return adminTabla();
    }
    const edit = b.dataset.x === 'edit';
    const vals = edit ? { ...fila, clave: '' } : {};
    const d = await formulario((edit ? 'Editar ' : 'Nuevo ') + ({usuarios:'usuario',sistemas:'sistema',cultivos:'cultivo',dispositivos:'dispositivo',sensores:'sensor',umbrales:'umbral'})[adminTab], camposDe(adminTab, edit), vals);
    if (!d) return;
    ['id_sistema', 'id_dispositivo'].forEach(k => { if (k in d) d[k] = Number(d[k]); });
    if (adminTab === 'usuarios' && !d.clave) delete d.clave;
    if (adminTab === 'sensores') d.unidad = null;
    if (adminTab === 'dispositivos' && edit) delete d.variables;
    const r = edit ? await API.put(ent.ruta + '/' + id, d) : await API.post(ent.ruta, d);
    toast('Guardado');
    if (r.api_key) await dialogoClave(r.api_key, r.aviso);
    adminTabla();
  } catch (e) { toast(e.message, true); if (b) b.disabled = false; }
});

iniciar();
