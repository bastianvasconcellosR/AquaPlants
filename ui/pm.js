// Pruebas manuales automatizadas (PM) de la interfaz con Playwright. Guarda capturas como evidencia.
//   node tests/ui/pm.js            (desde la raíz del repositorio)
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const RAIZ = path.resolve(__dirname, '..', '..');
const EV = path.join(RAIZ, 'docs', 'evidencias');
fs.mkdirSync(EV, { recursive: true });
const PUERTO = 8793, URL = `http://127.0.0.1:${PUERTO}`;
const ADMIN = ['admin@aquaplants.cl', 'AdminPruebas2026'], ENC = ['encargado@aquaplants.cl', 'Cultivo2026aq'];
const resultados = [];

function registrar(id, desc, esperado, obtenido, ok, evidencia) {
  resultados.push({ id, descripcion: desc, esperado, obtenido: String(obtenido), estado: ok ? 'Aprobado' : 'Fallido', evidencia: evidencia || '' });
  console.log(`${ok ? 'OK ' : 'FALLA'} ${id} ${desc}${ok ? '' : ' -> ' + obtenido}`);
}
const api = async (m, r, b, h = {}) => {
  const x = await fetch(URL + '/api/v1' + r, { method: m, headers: { 'Content-Type': 'application/json', ...h }, body: b ? JSON.stringify(b) : undefined });
  let j = null; try { j = await x.json(); } catch (e) {} return [x.status, j];
};

(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'aq_ui_'));
  const srv = spawn('python3', ['-m', 'uvicorn', 'backend.app.main:app', '--port', String(PUERTO), '--log-level', 'warning'], {
    cwd: RAIZ, env: { ...process.env, DATABASE_URL: `sqlite:///${dir}/ui.db`, JWT_SECRET: 'secreto-ui-0123456789abcdef0123456789', ADMIN_PASSWORD: ADMIN[1], BACKUP_DIR: dir + '/r', BACKUP_AUTO: '0', SEED_DEMO: '1', APP_ENV: 'test' }, stdio: 'ignore' });
  for (let i = 0; i < 100; i++) { try { if ((await fetch(URL + '/api/v1/health')).ok) break; } catch (e) {} await new Promise(r => setTimeout(r, 150)); }

  const [, la] = await api('POST', '/auth/login', { email: ADMIN[0], clave: ADMIN[1] }); const tokA = la.token;
  const H = { Authorization: 'Bearer ' + tokA };
  const [, sis] = await api('POST', '/sistemas', { nombre: 'Sistema UI' }, H);
  for (const [v, a, b] of [['ph', 5.5, 6.8], ['temperatura_agua', 18, 26]]) await api('POST', '/umbrales', { id_sistema: sis.id, variable: v, minimo: a, maximo: b }, H);
  const [, dev] = await api('POST', '/dispositivos', { id_sistema: sis.id, codigo: 'UI-001', nombre: 'Controlador UI', variables: ['ph', 'temperatura_agua'] }, H);
  const key = dev.api_key;

  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 1200, height: 800 } }); const p = await ctx.newPage();
  const ejecutadoXSS = []; await p.exposeFunction('__xss', () => ejecutadoXSS.push(1));
  p.on('dialog', d => { ejecutadoXSS.push(d.message()); d.dismiss(); });
  const shot = async (n) => { await p.screenshot({ path: path.join(EV, n + '.png') }); return `docs/evidencias/${n}.png`; };
  const login = async (u) => { await p.goto(URL); await p.fill('#l-email', u[0]); await p.fill('#l-clave', u[1]); await p.click('#form-login button'); await p.waitForSelector('#nav button'); };

  try {
    // PM-01
    await p.goto(URL); await p.fill('#l-email', ENC[0]); await p.fill('#l-clave', 'incorrecta99'); await p.click('#form-login button');
    await p.waitForSelector('#l-error:not([hidden])'); let msg = await p.textContent('#l-error');
    registrar('PM-01', 'Login con credenciales erróneas muestra mensaje claro y no ingresa', 'mensaje «Correo o contraseña incorrectos»; sigue en el login', msg, msg.includes('incorrectos') && await p.isVisible('#vista-login'), await shot('pm-01-login-error'));
    // PM-02
    await p.fill('#l-clave', ENC[1]); await p.click('#form-login button'); await p.waitForSelector('#nav button');
    let nav = await p.$$eval('#nav button', e => e.map(x => x.textContent));
    registrar('PM-02', 'Login correcto del Encargado: menú acorde al rol (sin Administración)', 've Estado, Alertas, Históricos, Bitácora; no ve Administración', nav.join(', '), nav.length === 4 && !nav.includes('Administración'));
    // PM-03: flujo completo medición → API → dashboard
    await api('POST', '/mediciones', { variable: 'ph', valor: 6.2 }, { 'X-API-Key': key });
    await api('POST', '/mediciones', { variable: 'temperatura_agua', valor: 22.5 }, { 'X-API-Key': key });
    await p.click('button[data-v=estado]'); await p.waitForSelector('#devs table');
    let txt = await p.textContent('#devs');
    const card = (await p.$$('#devs .card')).length;
    registrar('PM-03', 'Dashboard muestra última lectura, rango, condición y conexión del dispositivo', 'UI-001 «En línea», pH 6.2 Normal, temperatura 22.5 Normal',
      txt.replace(/\s+/g, ' ').slice(txt.indexOf('Controlador UI'), txt.indexOf('Controlador UI') + 220), /Controlador UI/.test(txt) && /En línea/.test(txt) && txt.includes('6.2') && txt.includes('22.5'), await shot('pm-03-dashboard'));
    // PM-04: alerta
    await api('POST', '/mediciones', { variable: 'ph', valor: 7.9, marca_tiempo: new Date(Date.now() - 60000).toISOString().slice(0, 19) + 'Z' }, { 'X-API-Key': key });
    await p.click('button[data-v=alertas]'); await p.waitForSelector('#lista table'); await p.selectOption('#f-est', 'Pendiente'); await p.waitForTimeout(500);
    let fila = await p.textContent('#lista tbody'); const ev1 = await shot('pm-04a-alerta-pendiente');
    await p.click('#lista button[data-a=proc]'); await p.waitForTimeout(700); await p.selectOption('#f-est', 'En proceso'); await p.waitForTimeout(500);
    const enProceso = (await p.textContent('#lista tbody')).includes('En proceso');
    await p.click('#lista button[data-a=res]'); await p.waitForSelector('#dlg[open]');
    await p.click('#dlg-ok'); await p.waitForTimeout(200);
    const errSinCausa = await p.textContent('#dlg-error'); const evErr = await shot('pm-05-resolver-sin-causa');
    registrar('PM-05', 'Resolver alerta sin causa: el formulario lo impide con mensaje', 'mensaje indicando que la causa es obligatoria', errSinCausa, /obligatorio/.test(errSinCausa), evErr);
    await p.fill('#f-causa', 'Se corrigió la dosificación de ácido'); await p.click('#dlg-ok'); await p.waitForTimeout(800);
    await p.selectOption('#f-est', 'Resuelta'); await p.waitForTimeout(500);
    const resuelta = await p.textContent('#lista tbody');
    registrar('PM-04', 'Alerta fuera de umbral: aparece Pendiente, se toma (En proceso) y se resuelve con causa', 'Pendiente visible → En proceso → Resuelta con la causa registrada',
      `pendiente visible=${/ph fuera de rango|Pendiente/.test(fila)}, en proceso=${enProceso}, resuelta con causa=${resuelta.includes('Se corrigió')}`, /Pendiente/.test(fila) && enProceso && resuelta.includes('Se corrigió la dosificación'), await shot('pm-04b-alerta-resuelta'));
    // PM-06 histórico
    await p.click('button[data-v=historico]'); await p.waitForSelector('#h-stats .kpi');
    const pix = await p.$eval('#h-cv', c => { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; });
    const csvEnc = await p.isVisible('#h-csv'); const stats = await p.textContent('#h-stats');
    registrar('PM-06', 'Histórico: gráfico dibujado con estadísticas; el Encargado no ve «Exportar CSV»', 'canvas con píxeles dibujados, 4 tarjetas de estadísticas y sin botón CSV', `píxeles=${pix}, csv visible=${csvEnc}`, pix > 500 && !csvEnc && /Mediciones/.test(stats), await shot('pm-06-historico'));
    // PM-07 bitácora
    await p.click('button[data-v=bitacora]'); await p.waitForSelector('#b-nuevo'); await p.click('#b-nuevo'); await p.waitForSelector('#dlg[open]');
    await p.selectOption('#f-id_cultivo', { index: 0 }); await p.fill('#f-accion', 'Prueba XSS'); await p.fill('#f-detalle', '<img src=x onerror="window.__xss()"><script>window.__xss()</script>');
    await p.click('#dlg-ok'); await p.waitForTimeout(900);
    const listaB = await p.textContent('#b-lista');
    registrar('PM-07', 'Texto con HTML/JavaScript en la bitácora se muestra como texto y no se ejecuta (XSS)', 'se ve el texto literal; ningún script se ejecuta', `literal visible=${listaB.includes('<img src=x')}, ejecuciones=${ejecutadoXSS.length}`, listaB.includes('<img src=x') && ejecutadoXSS.length === 0, await shot('pm-07-xss'));
    // PM-08 pérdida de conexión
    await p.click('button[data-v=estado]'); await p.waitForSelector('#devs table');
    await p.route('**/api/v1/dashboard/estado', r => r.abort());
    // el sondeo real es cada 30 s: se invoca la vista para no esperar; reutiliza los últimos datos recibidos
    await p.evaluate(async () => { await vEstado(); });
    await p.waitForTimeout(800);
    const aviso = await p.textContent('#aviso').catch(() => ''); const evCorte = await shot('pm-08-sin-conexion');
    await p.unroute('**/api/v1/dashboard/estado');
    registrar('PM-08', 'Pérdida de conexión del navegador con la API: aviso claro, sin pantalla en blanco', 'mensaje «Sin conexión con el servidor…» y/o error legible', (aviso || await p.textContent('#devs')).slice(0, 120), /Sin conexión/.test(aviso + await p.textContent('#devs')), evCorte);
    // PM-09 sesión expirada
    await p.evaluate(() => sessionStorage.setItem('aq_token', 'token.invalido.xxx')); await p.reload(); await p.waitForTimeout(700);
    const enLogin = await p.isVisible('#vista-login');
    registrar('PM-09', 'Token inválido/expirado: vuelve al login sin quedarse en pantalla rota', 'se muestra el formulario de login', `login visible=${enLogin}`, enLogin, await shot('pm-09-sesion-expirada'));
    // PM-10 admin CRUD
    await login(ADMIN); await p.click('button[data-v=admin]'); await p.waitForSelector('#a-body table');
    await p.click('button[data-t=dispositivos]'); await p.waitForSelector('#a-body table'); await p.click('button[data-x=nuevo]'); await p.waitForSelector('#dlg[open]');
    await p.fill('#f-codigo', 'UI-NUEVO'); await p.fill('#f-nombre', 'Dispositivo creado en la UI'); await p.click('#dlg-ok');
    await p.waitForSelector('code.key'); const claveVista = await p.textContent('code.key'); const evKey = await shot('pm-10-api-key');
    await p.click('#dlg-ok'); await p.waitForTimeout(700);
    const tabla = await p.textContent('#a-body'); const hayClaveEnTabla = tabla.includes(claveVista.trim());
    registrar('PM-10', 'Administrador crea dispositivo en la UI: la API Key se muestra una sola vez y no queda en la tabla', 'aparece diálogo con clave aq_…; luego el listado muestra el dispositivo sin la clave', `clave mostrada=${/^aq_\d+_/.test(claveVista.trim())}, en tabla=${hayClaveEnTabla}, dispositivo listado=${tabla.includes('UI-NUEVO')}`, /^aq_\d+_/.test(claveVista.trim()) && !hayClaveEnTabla && tabla.includes('UI-NUEVO'), evKey);
    // PM-11 validación de formulario
    await p.click('button[data-t=umbrales]'); await p.waitForSelector('#a-body table'); await p.click('#a-body button[data-x=edit]'); await p.waitForSelector('#dlg[open]');
    await p.fill('#f-minimo', '9'); await p.fill('#f-maximo', '3'); await p.click('#dlg-ok'); await p.waitForTimeout(800);
    const t = await p.textContent('#toast'); const evUmb = await shot('pm-11-validacion-umbral');
    registrar('PM-11', 'Umbral con mínimo mayor que máximo: la API lo rechaza y la UI informa el motivo', 'mensaje de error visible (mínimo debe ser menor que máximo)', t, /menor/.test(t), evUmb);
    // PM-12 menú administración + auditoría + respaldo
    await p.click('button[data-t=respaldos]'); await p.waitForSelector('button[data-x=resp]'); await p.click('button[data-x=resp]'); await p.waitForTimeout(1200);
    const resp = await p.textContent('#a-body tbody'); const evResp = await shot('pm-12-respaldos');
    registrar('PM-12', 'Respaldo manual desde la UI', 'aparece una fila «manual» con estado Completo', resp.replace(/\s+/g, ' ').slice(0, 100), /manual/.test(resp) && /Completo/.test(resp), evResp);
    // PM-13 responsive
    await p.setViewportSize({ width: 390, height: 800 }); await p.click('button[data-v=estado]'); await p.waitForSelector('#devs table'); await p.waitForTimeout(300);
    const ov = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    registrar('PM-13', 'Vista móvil (390 px): sin desplazamiento horizontal de la página', 'scrollWidth ≤ clientWidth', `desborde=${ov}px`, ov <= 1, await shot('pm-13-movil'));
    await p.setViewportSize({ width: 1200, height: 800 });
    // PM-15 informe de gestión + eliminar (borrado lógico) en el CRUD
    await p.setViewportSize({ width: 1200, height: 900 }); await p.goto(URL); await p.evaluate(() => sessionStorage.clear()); await login(ADMIN); await p.click('button[data-v=informe]'); await p.waitForSelector('#i-body h2'); await p.waitForTimeout(500);
    const inf = (await p.textContent('#i-body')).replace(/\s+/g, ' '); const evInf = await shot('pm-15-informe-gestion');
    registrar('PM-15', 'Informe de gestión visible desde la interfaz (Administrador/Supervisor)', 'aparecen resumen ejecutivo, variables, desempeño por dispositivo y alertas', inf.slice(0, 110), /Resumen ejecutivo/.test(inf) && /Variables monitoreadas/.test(inf) && /Alertas del período/.test(inf), evInf);
    // PM-14 teclado / accesibilidad básica
    await p.goto(URL); await p.evaluate(() => sessionStorage.clear()); await p.reload(); await p.waitForSelector('#form-login');
    await p.keyboard.press('Tab'); const foco1 = await p.evaluate(() => document.activeElement.id); await p.keyboard.press('Tab'); const foco2 = await p.evaluate(() => document.activeElement.id);
    const etiquetas = await p.$$eval('#form-login input', e => e.every(i => i.closest('label')));
    registrar('PM-14', 'Accesibilidad básica del login: orden de tabulación y campos etiquetados', 'Tab recorre correo → contraseña; ambos inputs dentro de <label>', `${foco1} → ${foco2}; etiquetados=${etiquetas}`, foco1 === 'l-email' && foco2 === 'l-clave' && etiquetas);
  } catch (e) {
    registrar('PM-ERR', 'Error inesperado en el script de pruebas de UI', 'sin errores', e.stack.split('\n').slice(0, 3).join(' | '), false);
  }
  await b.close(); srv.kill();
  fs.writeFileSync(path.join(EV, 'ui_resultados.json'), JSON.stringify(resultados, null, 2));
  const fallos = resultados.filter(r => r.estado !== 'Aprobado').length;
  console.log(`\nUI: ${resultados.length - fallos}/${resultados.length} aprobados`);
  process.exit(fallos ? 1 : 0);
})();
