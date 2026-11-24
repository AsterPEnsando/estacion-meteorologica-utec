// Dashboard remoto (GitHub Pages). Solo lectura de Firebase Realtime Database por REST.
// Estructura esperada (la escribe firebase_sync.py):
//   <root>/live            {state, platform, heartbeat(ms servidor), latest{...}, demo}
//   <root>/history/<ts_ms> {ts, timestamp, platform, temp_aht, temp_bmp, temp_avg, humidity, pressure, light, adc_max, light_pct, rain, rain_level, rain_adc}
const CFG = Object.assign({root: 'estacion', pollSeconds: 4, offlineSeconds: 30}, window.ESTACION_CONFIG || {});
const BASE = String(CFG.databaseURL || '').replace(/\/+$/, '') + '/' + CFG.root;

const paths={grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',chart:'M3 3v18h18 M6 15l5-5 4 3 6-8',history:'M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v5l3 2',cpu:'M6 6h12v12H6z M9 9h6v6H9z M9 2v4 M15 2v4 M9 18v4 M15 18v4 M2 9h4 M2 15h4 M18 9h4 M18 15h4',moon:'M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11',sun:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v2 M12 20v2 M2 12h2 M20 12h2 M5 5l1 1 M18 18l1 1 M5 19l1-1 M18 6l1-1',refresh:'M20 7a9 9 0 0 0-15-2L2 8 M2 2v6h6 M4 17a9 9 0 0 0 15 2l3-3 M16 16h6v6',download:'M12 3v12 M7 10l5 5 5-5 M4 16v5h16v-5',thermometer:'M9 14.5V5a3 3 0 0 1 6 0v9.5a5 5 0 1 1-6 0 M12 8v9 M12 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4',drop:'M12 2C9 7 4 11 4 15a8 8 0 0 0 16 0c0-4-5-8-8-13z',pressure:'M4 18a9 9 0 1 1 16 0 M7 18h10 M12 14l4-5 M5 10l2 1 M10 5v2 M17 7l-1 2',cloud:'M6 18a5 5 0 1 1 1-10 6 6 0 0 1 11 2 4 4 0 0 1 0 8z',rain:'M5 15a4 4 0 1 1 2-8 6 6 0 0 1 11 2 3 3 0 0 1 1 6 M8 18l-1 3 M13 18l-1 3 M18 18l-1 3'};
const icon=n=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[n]||paths.grid}"/></svg>`;
document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const PLATFORMS={atmega328p:'ATmega328P',psoc5lp:'PSoC 5LP'}, COLORS={atmega328p:'#3b82f6',psoc5lp:'#f59e0b'}, RAIN=['Seco','Moderado','Intenso'];
const fmt=(v,d=1)=>v==null?'—':Number(v).toLocaleString('es-PE',{minimumFractionDigits:d,maximumFractionDigits:d});
const when=ms=>ms?new Date(ms).toLocaleTimeString('es-PE',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
const stamp=r=>r.ts??Date.parse(r.timestamp);
function toast(m){$('toast').textContent=m;$('toast').hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>$('toast').hidden=true,4500)}
async function get(path,query=''){const res=await fetch(`${BASE}/${path}.json${query}`,{cache:'no-store'});if(!res.ok)throw Error(`Firebase respondió ${res.status}`);return res.json()}

// ---- Tarjetas ----
const specs=[['temp_aht','Temperatura ambiental','°C','thermometer','AHT20 · Temperatura principal'],['humidity','Humedad relativa','%','drop','AHT20 · Humedad ambiental'],['pressure','Presión atmosférica','hPa','pressure','BMP280 · Presión absoluta'],['light_pct','Intensidad de luz','%','sun','Promedio 3 LDR · % del ADC, no lux'],['rain_level','Estado de lluvia','','cloud','FC-37 · Humedad superficial de placa'],['temp_avg','Temperatura promedio','°C','thermometer','Media AHT20 y BMP280']];
$('metrics').innerHTML=specs.map(([k,n,u,ic,note])=>`<article class="metric" id="metric-${k}"><div class="metric-top"><span>${n}</span><span class="metric-icon">${icon(ic)}</span></div><div class="metric-value ${k==='rain_level'?'rain':''}"><span class="value">—</span><small>${u}</small></div><div class="metric-bottom"><span class="updated-time">Esperando medición</span><span class="trend"></span></div><div class="metric-note">${note}</div></article>`).join('');
function renderCards(r,online){specs.forEach(([k,,,ic])=>{const card=$('metric-'+k),v=r?.[k];card.classList.toggle('offline',!!r&&!online);card.querySelector('.value').textContent=k==='rain_level'?(v==null?'Sin datos':RAIN[v]??'—'):fmt(v,1);card.querySelector('.updated-time').textContent=r&&v!=null?(online?`Actualizado ${when(stamp(r))}`:`Última lectura ${when(stamp(r))} · sin conexión`):'Sin lectura válida';card.querySelector('.trend').textContent=k==='light_pct'&&r?.light!=null?`ADC ${r.light} / ${r.adc_max}`:k==='rain_level'?'0 seco · 1 moderado · 2 intenso':'';const box=card.querySelector('.metric-icon');box.innerHTML=icon(k==='rain_level'&&v>0?'rain':ic);box.classList.toggle('wet',k==='rain_level'&&v>0);if(k==='humidity'&&v!=null)box.style.background=`linear-gradient(to top, var(--blue) ${v}%, var(--soft) ${v}%)`;if(k==='light_pct')box.style.opacity=v==null?'1':String(.35+.65*v/100)})}

// ---- Estado en vivo ----
let live=null,lastOk=null,serverOffset=0;
async function poll(){try{live=await get('live');lastOk=Date.now();renderLive()}catch(e){renderLive(e)}}
function renderLive(err){
  // El latido lo fija el servidor de Firebase: se compara con la hora del navegador, que puede tener desfase.
  const beatAge=live?.heartbeat?(Date.now()-live.heartbeat)/1000:null;
  const online=!err&&beatAge!=null&&beatAge<CFG.offlineSeconds&&live.state==='connected'&&!live.demo;
  const label=err?'Sin acceso a Firebase':!live?'El colector aún no publica datos':live.demo?'Colector en modo demostración (no se publican datos)':beatAge==null||beatAge>=CFG.offlineSeconds?'Colector desconectado':live.state==='connected'?'En línea':live.state==='stale'?'Sin datos recientes del HC-05':live.state==='connecting'?'Colector conectando al HC-05':'HC-05 desconectado';
  $('connection').textContent=label;$('connection-dot').className='dot '+(online?'connected':err||!live?'':'stale');
  const r=live?.latest||null;$('platform-label').textContent='Plataforma: '+(PLATFORMS[r?.platform]||'—');
  $('last-received').textContent=r?`Última lectura · ${new Date(stamp(r)).toLocaleString('es-PE')}`:'Sin mediciones recibidas';
  renderCards(r,online);
  const diag=[['Estado del colector',label],['Plataforma',PLATFORMS[r?.platform]||'—'],['Último latido',beatAge==null?'—':`hace ${Math.max(0,Math.round(beatAge))} s`],['Última lectura',r?when(stamp(r)):'—'],['Registros en vista',records.length.toLocaleString('es-PE')],['Consulta',`cada ${CFG.pollSeconds} s`]];
  $('diagnostics').innerHTML=diag.map(([k,v])=>`<div class="diagnostic"><span>${k}</span><strong>${esc(v)}</strong></div>`).join('');
  $('system-error').hidden=!err;$('system-error').textContent=err?`${err.message}. Revisa databaseURL en config.js y las reglas de lectura.`:'';
}

// ---- Historial ----
let records=[],page=1,charts={};
const filtered=()=>$('platform').value==='all'?records:records.filter(r=>r.platform===$('platform').value);
async function loadHistory(){try{const since=Date.now()-Number($('range').value)*3600e3;const data=await get('history',`?orderBy=%22%24key%22&startAt=%22${since}%22&limitToLast=5000`)||{};records=Object.values(data).filter(r=>r&&r.ts).sort((a,b)=>a.ts-b.ts);page=1;renderHistory()}catch(e){toast('No se pudo leer el historial: '+e.message)}}
function renderHistory(){const rows=filtered().slice().reverse(),total=rows.length,view=rows.slice((page-1)*25,page*25);
  $('rows').innerHTML=view.length?view.map(r=>`<tr><td>${esc(new Date(r.ts).toLocaleDateString('es-PE'))}<small>${when(r.ts)}</small></td><td><span class="platform-chip">${esc(PLATFORMS[r.platform]||r.platform)}</span></td>${['temp_aht','temp_bmp','temp_avg','humidity','pressure'].map(k=>`<td>${fmt(r[k],1)}</td>`).join('')}<td>${r.light==null?'—':`${fmt(r.light_pct,1)}<small>ADC ${r.light}</small>`}</td><td>${esc(RAIN[r.rain_level]??'—')}</td></tr>`).join(''):'<tr><td colspan="9" class="empty">No hay mediciones en este intervalo.</td></tr>';
  $('page-info').textContent=total?`${(page-1)*25+1}–${Math.min(page*25,total)} de ${total} registros`:'0 registros';$('prev').disabled=page<=1;$('next').disabled=page*25>=total;drawCharts(filtered())}
const chartSpecs=[['temp_aht','Temperatura AHT20','°C'],['humidity','Humedad relativa','%'],['pressure','Presión atmosférica','hPa'],['light_pct','Intensidad de luz','% relativo · no lux'],['rain_level','Estado de lluvia','0 seco · 1 moderado · 2 intenso']];
$('chart-grid').innerHTML=chartSpecs.map(([k,l,u])=>`<article class="chart-panel"><div class="chart-heading"><h3>${l}</h3><span>${u}</span></div><div class="chart-body"><canvas id="chart-${k}" role="img" aria-label="Histórico de ${l}"></canvas><div id="empty-${k}" class="chart-empty"><strong>Sin mediciones</strong><span>No hay registros en el intervalo</span></div></div></article>`).join('');
function drawCharts(rows){if(typeof Chart==='undefined')return;const css=getComputedStyle(document.documentElement),muted=css.getPropertyValue('--muted').trim(),grid=css.getPropertyValue('--grid').trim();const present=Object.keys(PLATFORMS).filter(p=>rows.some(r=>r.platform===p));
  chartSpecs.forEach(([k,,u])=>{charts[k]?.destroy();$('empty-'+k).hidden=rows.some(r=>r[k]!=null);
    // Una serie por plataforma: las lecturas no son simultáneas, así que los huecos se dejan visibles.
    const datasets=present.map(p=>({label:PLATFORMS[p],data:rows.map(r=>r.platform===p?r[k]??null:null),borderColor:COLORS[p],backgroundColor:COLORS[p]+'18',fill:false,stepped:k==='rain_level',tension:.25,pointRadius:rows.length<40?2:0,pointHitRadius:10,borderWidth:2,spanGaps:false}));
    charts[k]=new Chart($('chart-'+k),{type:'line',data:{labels:rows.map(r=>r.ts),datasets},options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:present.length>1,position:'bottom',labels:{color:muted,boxWidth:12,font:{size:9}}},tooltip:{callbacks:{title:i=>new Date(+i[0].label).toLocaleString('es-PE'),label:i=>i.raw==null?null:`${i.dataset.label}: ${k==='rain_level'?RAIN[i.raw]:i.raw} ${k==='rain_level'?'':u}`}}},scales:{x:{grid:{display:false},border:{display:false},ticks:{color:muted,maxTicksLimit:6,maxRotation:0,font:{size:9},callback:function(v){return new Date(+this.getLabelForValue(v)).toLocaleString('es-PE',{hour:'2-digit',minute:'2-digit',...($('range').value==='168'?{day:'2-digit',month:'short'}:{})})}}},y:{min:['rain_level','humidity','light_pct'].includes(k)?0:undefined,max:k==='rain_level'?2:['humidity','light_pct'].includes(k)?100:undefined,border:{display:false},grid:{color:grid},ticks:{color:muted,maxTicksLimit:5,precision:k==='rain_level'?0:undefined,font:{size:9}}}}}})})}

// ---- Exportación CSV (en el navegador) ----
$('export').onclick=()=>{const cols=['timestamp','platform','temp_aht','temp_bmp','temp_avg','humidity','pressure','light','adc_max','light_pct','rain_level','rain_adc'];const lines=[cols.join(',')].concat(filtered().map(r=>cols.map(c=>r[c]??'').join(',')));const url=URL.createObjectURL(new Blob(['﻿'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`meteorologia-remoto-${$('platform').value}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`CSV exportado · ${filtered().length} registros`)};

// ---- Controles ----
function updateTheme(){const dark=document.documentElement.dataset.theme==='dark';$('theme').innerHTML=icon(dark?'sun':'moon');drawCharts(filtered())}
$('theme').onclick=()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{localStorage.setItem('weather-theme',t)}catch(e){}updateTheme()};
$('range').onchange=loadHistory;$('refresh').onclick=loadHistory;$('platform').onchange=()=>{page=1;renderHistory()};
$('prev').onclick=()=>{if(page>1){page--;renderHistory()}};$('next').onclick=()=>{if(page*25<filtered().length){page++;renderHistory()}};
document.querySelectorAll('nav a').forEach(a=>a.onclick=()=>{document.querySelectorAll('nav a').forEach(x=>x.classList.remove('active'));a.classList.add('active')});
setInterval(()=>$('clock').textContent=new Date().toLocaleString('es-PE',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}),1000);

if(!CFG.databaseURL){
  document.querySelector('main').insertAdjacentHTML('afterbegin','<div class="panel setup"><h2>Falta configurar Firebase</h2><p>Edita <code>docs/config.js</code> y completa <code>databaseURL</code> con la URL de tu Realtime Database. Ver README, sección «Visualización remota».</p></div>');
  $('connection').textContent='Sin configurar';
}else{
  $('poll-label').textContent=`Actualización automática · ${CFG.pollSeconds} s`;
  updateTheme();poll();loadHistory();setInterval(poll,CFG.pollSeconds*1000);setInterval(loadHistory,60000);
}
