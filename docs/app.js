// Estación Meteorológica UTEC · vista remota (GitHub Pages, solo lectura de Firebase por REST).
// Estructura que escribe firebase_sync.py:
//   <root>/live            {state, platform, heartbeat(ms servidor), latest{...}, demo}
//   <root>/history/<ts_ms> {ts, platform, temp_aht, temp_bmp, temp_avg, humidity, pressure, light, adc_max, light_pct, rain_level, ...}
const CFG = Object.assign({root:'estacion', pollSeconds:4, offlineSeconds:30}, window.ESTACION_CONFIG || {});
const BASE = String(CFG.databaseURL || '').replace(/\/+$/, '') + '/' + CFG.root;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const PLAT = {atmega328p:'ATmega328P', psoc5lp:'PSoC 5LP'};
const RAIN = ['Sin lluvia','Lluvia moderada','Lluvia intensa'];
const METRICS = {
  temp_aht:{name:'Temperatura', unit:'°C', d:1},
  humidity:{name:'Humedad', unit:'%', d:0},
  pressure:{name:'Presión', unit:'hPa', d:1},
  light_pct:{name:'Luminosidad', unit:'%', d:0},
};
const num = (v, d=1) => v == null ? '--' : Number(v).toLocaleString('es-PE', {minimumFractionDigits:d, maximumFractionDigits:d});
const cell = (v, d, u) => v == null ? '<span style="color:var(--ink-3)">—</span>' : `${num(v, d)} ${u}`;
const clock = ms => new Date(ms).toLocaleTimeString('es-PE', {hour:'2-digit', minute:'2-digit'});
const ago = ms => { const s = Math.max(0, (Date.now()-ms)/1000); return s < 60 ? 'hace unos segundos' : s < 3600 ? `hace ${Math.round(s/60)} min` : s < 86400 ? `hace ${Math.round(s/3600)} h` : new Date(ms).toLocaleDateString('es-PE', {day:'numeric', month:'short'}); };
const stamp = r => r.ts ?? Date.parse(r.timestamp);
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function toast(m){ $('toast').textContent = m; $('toast').hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => $('toast').hidden = true, 3500); }

// ---- Íconos ----
const ICONS = {
  drop:'<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  gauge:'<path d="M4 17a8 8 0 1 1 16 0"/><path d="m12 13 4-4"/><circle cx="12" cy="14" r="1.5"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  rain:'<path d="M7 15a4 4 0 1 1 .5-8 5.5 5.5 0 0 1 10.4 1.5A3.5 3.5 0 0 1 17.5 15"/><path d="m9 18-1 2M13 18l-1 2M17 18l-1 2"/>',
  download:'<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  moon:'<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
};
const icon = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[n]}</svg>`;
document.querySelectorAll('[data-i]').forEach(el => el.innerHTML = icon(el.dataset.i));

// Ilustraciones del héroe (decorativas)
const CLOUD = (x, y, s, o=1) => `<g transform="translate(${x} ${y}) scale(${s})" opacity="${o}"><path d="M30 70h80a28 28 0 0 0 0-56 40 40 0 0 0-76 10A24 24 0 0 0 30 70z" fill="#fff"/></g>`;
const SUN = (cx, cy, r) => `<g class="sun-rays" style="transform-origin:${cx}px ${cy}px">${Array.from({length:12}, (_, i) => `<rect x="${cx-3}" y="${cy-r-30}" width="6" height="18" rx="3" fill="#ffe08a" transform="rotate(${i*30} ${cx} ${cy})"/>`).join('')}</g><circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#sg)"/>`;
const DEFS = '<defs><radialGradient id="sg" cx="40%" cy="35%"><stop offset="0" stop-color="#fff6c9"/><stop offset=".6" stop-color="#ffd24d"/><stop offset="1" stop-color="#ffb020"/></radialGradient></defs>';
const ART = {
  sun: `<svg viewBox="0 0 200 200">${DEFS}${SUN(100,100,46)}</svg>`,
  partly: `<svg viewBox="0 0 200 200">${DEFS}${SUN(118,78,38)}<g class="cloud-float">${CLOUD(18,92,1.15)}</g></svg>`,
  cloud: `<svg viewBox="0 0 200 200"><g class="cloud-float">${CLOUD(48,46,.95,.55)}${CLOUD(14,82,1.25)}</g></svg>`,
  rain: `<svg viewBox="0 0 200 200"><g class="cloud-float">${CLOUD(14,40,1.25)}</g>${[40,70,100,130,160].map((x, i) => `<rect class="raindrop" style="animation-delay:${i*.23}s" x="${x}" y="140" width="5" height="18" rx="2.5" fill="#cfe6ff"/>`).join('')}</svg>`,
};

// ---- Datos ----
async function get(path, query=''){ const res = await fetch(`${BASE}/${path}.json${query}`, {cache:'no-store'}); if(!res.ok) throw Error(res.status); return res.json(); }
let live = null, liveErr = null, records = [], state = {range:24, metric:'temp_aht', platform:'all', page:1}, chart = null;

async function poll(){ try { live = await get('live'); liveErr = null; } catch(e) { liveErr = e; } renderLive(); }
async function loadHistory(){
  try {
    const since = Date.now() - state.range*3600e3;
    const data = await get('history', `?orderBy=%22%24key%22&startAt=%22${since}%22&limitToLast=5000`) || {};
    records = Object.values(data).filter(r => r && r.ts).sort((a, b) => a.ts - b.ts);
  } catch(e) { toast('No se pudo cargar el historial'); }
  renderAll();
}
const isOnline = () => !liveErr && live?.heartbeat && (Date.now()-live.heartbeat)/1000 < CFG.offlineSeconds && live.state === 'connected' && !live.demo;
const view = () => state.platform === 'all' ? records : records.filter(r => r.platform === state.platform);

// ---- Héroe y tarjetas ----
function renderLive(){
  const online = isOnline(), r = live?.latest || null;
  $('live').className = 'live ' + (online ? 'on' : 'off');
  $('live-text').textContent = online ? 'En vivo' : liveErr ? 'Sin servidor' : 'Sin conexión';
  const banner = liveErr ? 'No se pudo conectar con el servidor de datos. Reintentando…'
    : !r ? 'La estación aún no ha enviado mediciones.'
    : !online ? `La estación no está transmitiendo en este momento. Se muestran los últimos datos recibidos (${ago(stamp(r))}).` : '';
  $('banner').hidden = !banner; $('banner-text').textContent = banner;

  const light = r?.light_pct, rain = r?.rain_level ?? 0;
  $('hero-temp').textContent = r?.temp_aht != null ? Math.round(r.temp_aht) : '--';
  const lightTxt = light == null ? '' : light >= 66 ? 'ambiente luminoso' : light >= 33 ? 'luz moderada' : 'poca luz';
  $('hero-condition').textContent = r ? (rain > 0 ? RAIN[rain] : `Sin lluvia${lightTxt ? ' · ' + lightTxt : ''}`) : 'Esperando datos de la estación';
  const art = rain > 0 ? 'rain' : light == null ? 'cloud' : light >= 66 ? 'sun' : light >= 33 ? 'partly' : 'cloud';
  if ($('hero-art').dataset.k !== art) { $('hero-art').innerHTML = ART[art]; $('hero-art').dataset.k = art; }
  $('hero').classList.toggle('rain', rain > 0); $('hero').classList.toggle('dim', rain === 0 && light != null && light < 33);
  $('hero-platform').textContent = r?.platform ? `Medido por ${PLAT[r.platform]}` : 'Sin plataforma activa';
  $('hero-dot').style.background = r?.platform ? css(r.platform === 'psoc5lp' ? '--psoc' : '--avr') : '#fff';
  $('hero-updated').textContent = r ? `Actualizado ${ago(stamp(r))}` : '';

  const tile = (id, val, sub, meter) => { const t = $(id); t.classList.toggle('offline', !!r && !online); t.querySelector('.v').textContent = val; t.querySelector('.s').innerHTML = sub; if (meter != null) t.querySelector('.meter i').style.width = Math.max(0, Math.min(100, meter)) + '%'; };
  const hum = r?.humidity;
  tile('t-hum', num(hum, 0), hum == null ? 'Humedad relativa del aire' : hum > 70 ? 'Ambiente húmedo' : hum >= 40 ? 'Nivel confortable' : 'Ambiente seco', hum ?? 0);
  tile('t-pres', num(r?.pressure, 1), presTrend(r));
  tile('t-light', num(light, 0), light == null ? 'Nivel de luz ambiental' : `Nivel ${light >= 66 ? 'alto' : light >= 33 ? 'medio' : 'bajo'}`, light ?? 0);
  const rt = $('t-rain'); rt.querySelector('.v').innerHTML = r ? `<span class="rain-badge lvl${rain}">${RAIN[rain]}</span>` : '--';
  rt.classList.toggle('offline', !!r && !online);
  renderPlatforms();
}
function presTrend(r){
  if (r?.pressure == null) return 'Presión atmosférica';
  const ref = records.filter(x => x.platform === r.platform && x.pressure != null && stamp(r) - x.ts >= 50*60e3).at(-1);
  if (!ref) return 'Presión atmosférica';
  const d = r.pressure - ref.pressure;
  return Math.abs(d) < .1 ? 'Estable en la última hora' : `<span class="${d > 0 ? 'trend-up' : 'trend-down'}">${d > 0 ? '▲' : '▼'} ${num(Math.abs(d), 1)} hPa</span> en la última hora`;
}

// ---- Plataformas ----
function renderPlatforms(){
  Object.keys(PLAT).forEach(p => {
    const el = $('p-' + p), rows = records.filter(r => r.platform === p), temps = rows.map(r => r.temp_aht).filter(v => v != null);
    el.querySelector('.n').textContent = rows.length.toLocaleString('es-PE');
    el.querySelector('.t').textContent = temps.length ? num(temps.reduce((a, b) => a + b, 0) / temps.length, 1) + ' °C' : '--';
    const last = live?.latest?.platform === p ? stamp(live.latest) : rows.at(-1)?.ts;
    el.querySelector('.l').textContent = last ? (Date.now() - last < 120e3 ? 'Ahora' : ago(last)) : '--';
    el.querySelector('.badge-live').hidden = !(isOnline() && live?.platform === p);
  });
}

// ---- Gráfica ----
const crosshair = {id:'crosshair', afterDraw(c){ const a = c.tooltip?.getActiveElements?.(); if (!a?.length) return; const x = a[0].element.x, {top, bottom} = c.chartArea, g = c.ctx; g.save(); g.strokeStyle = css('--ink-3'); g.globalAlpha = .5; g.setLineDash([4, 4]); g.beginPath(); g.moveTo(x, top); g.lineTo(x, bottom); g.stroke(); g.restore(); }};
function renderChart(){
  if (typeof Chart === 'undefined') return;
  const m = METRICS[state.metric], rows = view(), vals = rows.map(r => r[state.metric]).filter(v => v != null);
  $('chart-title').textContent = `${m.name} promedio del periodo`;
  $('chart-big').innerHTML = vals.length ? `${num(vals.reduce((a, b) => a + b, 0) / vals.length, m.d)}<small>${m.unit} · mín ${num(Math.min(...vals), m.d)} · máx ${num(Math.max(...vals), m.d)}</small>` : '--';
  $('chart-empty').hidden = vals.length > 0;
  const present = Object.keys(PLAT).filter(p => rows.some(r => r.platform === p && r[state.metric] != null));
  $('legend').innerHTML = present.map(p => `<span><i style="background:var(${p === 'psoc5lp' ? '--psoc' : '--avr'})"></i>${PLAT[p]}</span>`).join('');
  const ink3 = css('--ink-3'), grid = css('--grid');
  const datasets = present.map(p => {
    const color = css(p === 'psoc5lp' ? '--psoc' : '--avr');
    return {label:PLAT[p], data:rows.map(r => r.platform === p ? r[state.metric] ?? null : null), borderColor:color, borderWidth:2, tension:.35, spanGaps:false,
      pointRadius:rows.length < 30 ? 3 : 0, pointHoverRadius:5, pointBackgroundColor:color, pointBorderColor:css('--card'), pointBorderWidth:2, pointHitRadius:12, fill:present.length > 1 ? false : 'origin',
      backgroundColor:ctx => { const a = ctx.chart.chartArea; if (!a) return 'transparent'; const g = ctx.chart.ctx.createLinearGradient(0, a.top, 0, a.bottom); g.addColorStop(0, color + '40'); g.addColorStop(1, color + '00'); return g; }};
  });
  chart?.destroy();
  chart = new Chart($('chart'), {type:'line', data:{labels:rows.map(r => r.ts), datasets}, plugins:[crosshair],
    options:{responsive:true, maintainAspectRatio:false, animation:{duration:400}, interaction:{mode:'index', intersect:false},
      plugins:{legend:{display:false}, tooltip:{backgroundColor:css('--card'), titleColor:css('--ink'), bodyColor:css('--ink-2'), borderColor:css('--border'), borderWidth:1, padding:12, cornerRadius:12, boxPadding:6, usePointStyle:true,
        filter:i => i.raw != null, callbacks:{title:i => new Date(+i[0].label).toLocaleString('es-PE', {day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'}), label:i => ` ${i.dataset.label}: ${num(i.raw, m.d)} ${m.unit}`}}},
      scales:{x:{grid:{display:false}, border:{display:false}, ticks:{color:ink3, maxTicksLimit:6, maxRotation:0, font:{size:11}, callback(v){ const d = new Date(+this.getLabelForValue(v)); return state.range > 24 ? d.toLocaleDateString('es-PE', {day:'numeric', month:'short'}) : clock(d); }}},
        y:{grace:'10%', min:['humidity', 'light_pct'].includes(state.metric) ? 0 : undefined, max:['humidity', 'light_pct'].includes(state.metric) ? 100 : undefined, border:{display:false}, grid:{color:grid}, ticks:{color:ink3, maxTicksLimit:5, font:{size:11}}}}}});
}

// ---- Historial ----
function renderTable(){
  const rows = view().slice().reverse(), total = rows.length, pages = Math.max(1, Math.ceil(total / 10));
  state.page = Math.min(state.page, pages);
  const part = rows.slice((state.page - 1) * 10, state.page * 10);
  $('rows').innerHTML = part.length ? part.map(r => `<tr>
    <td>${esc(new Date(r.ts).toLocaleDateString('es-PE', {day:'numeric', month:'short'}))}<small>${clock(r.ts)}</small></td>
    <td><span class="pdot"><i style="background:var(${r.platform === 'psoc5lp' ? '--psoc' : '--avr'})"></i>${esc(PLAT[r.platform] || r.platform)}</span></td>
    <td class="num">${cell(r.temp_aht, 1, '°C')}</td><td class="num">${cell(r.humidity, 0, '%')}</td><td class="num">${cell(r.pressure, 1, 'hPa')}</td><td class="num">${cell(r.light_pct, 0, '%')}</td>
    <td><span class="rain-badge lvl${r.rain_level ?? 0}">${RAIN[r.rain_level ?? 0]}</span></td></tr>`).join('')
    : '<tr><td colspan="7" style="text-align:center;color:var(--ink-3);padding:36px">No hay mediciones en este periodo</td></tr>';
  $('page-info').textContent = total ? `${(state.page - 1) * 10 + 1}–${Math.min(state.page * 10, total)} de ${total.toLocaleString('es-PE')} registros` : '';
  $('prev').disabled = state.page <= 1; $('next').disabled = state.page >= pages;
}
function renderHeroRange(){
  const temps = records.map(r => r.temp_aht).filter(v => v != null);
  $('hero-max').textContent = temps.length ? Math.round(Math.max(...temps)) + '°' : '--';
  $('hero-min').textContent = temps.length ? Math.round(Math.min(...temps)) + '°' : '--';
  $('hero-range-label').textContent = {1:'última hora', 6:'últimas 6 h', 24:'últimas 24 h', 168:'últimos 7 días'}[state.range];
}
function renderAll(){ renderHeroRange(); renderChart(); renderTable(); renderLive(); }

// ---- Controles ----
function seg(id, key, after){ $(id).addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; $(id).querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', x === b)); state[key] = key === 'range' ? +b.dataset.v : b.dataset.v; state.page = 1; after(); }); }
seg('range', 'range', loadHistory); seg('metric', 'metric', renderChart); seg('platform', 'platform', () => { renderChart(); renderTable(); });
$('prev').onclick = () => { state.page--; renderTable(); }; $('next').onclick = () => { state.page++; renderTable(); };
$('export').onclick = () => {
  const cols = [['timestamp','Fecha y hora'],['platform','Plataforma'],['temp_aht','Temperatura AHT20 (°C)'],['temp_bmp','Temperatura BMP280 (°C)'],['humidity','Humedad (%)'],['pressure','Presión (hPa)'],['light_pct','Luz relativa (%)'],['light','Luz ADC'],['adc_max','ADC máximo'],['rain_level','Lluvia (0/1/2)']];
  const lines = [cols.map(c => c[1]).join(',')].concat(view().map(r => cols.map(([k]) => k === 'timestamp' ? new Date(r.ts).toISOString() : k === 'platform' ? PLAT[r.platform] || r.platform : r[k] ?? '').join(',')));
  const url = URL.createObjectURL(new Blob(['﻿' + lines.join('\r\n')], {type:'text/csv;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url; a.download = `estacion-utec-${state.platform}-${state.range}h.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(`CSV descargado · ${view().length} registros`);
};
const isDark = () => document.documentElement.dataset.theme ? document.documentElement.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
function paintTheme(){ $('theme').innerHTML = icon(isDark() ? 'sun' : 'moon'); $('theme').setAttribute('aria-label', isDark() ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'); renderAll(); }
$('theme').onclick = () => { const t = isDark() ? 'light' : 'dark'; document.documentElement.dataset.theme = t; try { localStorage.setItem('weather-theme', t); } catch(e) {} paintTheme(); };
matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', paintTheme);

if (!CFG.databaseURL) {
  $('hero').insertAdjacentHTML('afterend', '<div class="card setup"><h2>Falta configurar la fuente de datos</h2><p>Completa <code>databaseURL</code> en <code>docs/config.js</code>.</p></div>');
} else {
  paintTheme(); poll(); loadHistory();
  setInterval(poll, CFG.pollSeconds * 1000); setInterval(loadHistory, 60000); setInterval(() => { renderLive(); }, 15000);
}
