/* Gráfico de línea en canvas (sin librerías externas). Dibuja la serie y la banda del umbral. */
function dibujarLinea(canvas, puntos, { minimo = null, maximo = null, unidad = '' } = {}) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext('2d');
  g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);
  g.font = '11px Tahoma, sans-serif';
  if (!puntos.length) {
    g.fillStyle = '#595959'; g.textAlign = 'center';
    g.fillText('Sin mediciones en el período seleccionado', w / 2, h / 2);
    return;
  }
  const L = 48, R = 12, T = 12, B = 26;
  const xs = puntos.map(p => Date.parse(p.t)), ys = puntos.map(p => p.v);
  let y0 = Math.min(...ys), y1 = Math.max(...ys);
  if (minimo !== null) y0 = Math.min(y0, minimo);
  if (maximo !== null) y1 = Math.max(y1, maximo);
  const pad = (y1 - y0 || 1) * 0.1; y0 -= pad; y1 += pad;
  const x0 = xs[0], x1 = xs[xs.length - 1] || x0 + 1;
  const X = t => L + (w - L - R) * ((t - x0) / ((x1 - x0) || 1));
  const Y = v => T + (h - T - B) * (1 - (v - y0) / (y1 - y0));
  if (minimo !== null && maximo !== null) {
    g.fillStyle = 'rgba(46,125,79,.12)';
    g.fillRect(L, Y(maximo), w - L - R, Y(minimo) - Y(maximo));
  }
  g.strokeStyle = '#D8E4D5'; g.fillStyle = '#595959'; g.textAlign = 'right'; g.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = y0 + (y1 - y0) * i / 4, y = Y(v);
    g.beginPath(); g.moveTo(L, y); g.lineTo(w - R, y); g.stroke();
    g.fillText(v.toFixed(2), L - 6, y + 4);
  }
  g.textAlign = 'center';
  for (let i = 0; i <= 4; i++) {
    const t = x0 + (x1 - x0) * i / 4;
    const d = new Date(t);
    const etq = (x1 - x0) > 2 * 86400000
      ? d.toLocaleDateString('es-CL', { day: '2-digit', month: '2-digit' })
      : d.toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' });
    g.fillText(etq, X(t), h - 8);
  }
  g.setLineDash([5, 4]); g.strokeStyle = '#B00000';
  [minimo, maximo].forEach(v => { if (v !== null) { g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(w - R, Y(v)); g.stroke(); } });
  g.setLineDash([]);
  g.strokeStyle = '#1F5D3A'; g.lineWidth = 1.6; g.beginPath();
  puntos.forEach((p, i) => { const x = X(Date.parse(p.t)), y = Y(p.v); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.stroke();
  puntos.forEach(p => {
    if ((minimo !== null && p.v < minimo) || (maximo !== null && p.v > maximo)) {
      g.fillStyle = '#C62828'; g.beginPath(); g.arc(X(Date.parse(p.t)), Y(p.v), 3, 0, 6.3); g.fill();
    }
  });
}
