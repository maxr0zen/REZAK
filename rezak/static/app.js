'use strict';
const paths = {
  overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  twitch:'M5 3h16v12l-6 6h-4v-4H5V3z M10 7v6 M16 7v6',
  queue:'M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01',
  clips:'m9 8 7 4-7 4V8z M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z',
  settings:'m9 3-1 3-3 1 1 3-2 2 2 2-1 3 3 1 1 3h4l1-3 3-1-1-3 2-2-2-2 1-3-3-1-1-3H9z M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  plus:'M12 5v14 M5 12h14', upload:'M12 16V3 m-5 5 5-5 5 5 M4 15v5h16v-5',
  file:'M6 3h8l4 4v14H6V3z M14 3v5h4 M9 13h6 M9 17h4',
  chevron:'m9 5 7 7-7 7', arrow:'M5 12h14 m-5-5 5 5-5 5',
  refresh:'M20 7v5h-5 M4 17v-5h5 M6 6a8 8 0 0 1 13 3 M5 15a8 8 0 0 0 13 3',
  close:'m6 6 12 12 M6 18 18 6', pause:'M8 5v14 M16 5v14', play:'m8 4 12 8-12 8V4z',
  terminal:'m5 7 4 5-4 5 M12 17h7', download:'M12 3v12 m-5-5 5 5 5-5 M4 17v4h16v-4',
  stop:'M6 6h12v12H6z', check:'m5 12 4 4L19 6', clock:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l3 2',
  chip:'M6 6h12v12H6z M9 9h6v6H9z M9 2v4 M15 2v4 M9 18v4 M15 18v4 M2 9h4 M2 15h4 M18 9h4 M18 15h4',
  info:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7h.01',
  trash:'M3 6h18 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7',
  folder:'M3 6h7l2 2h9v12H3V6z', record:'M12 5a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
  external:'M14 3h7v7 M21 3 10 14 M10 4H4v16h16v-6', filter:'M3 5h18 M6 12h12 M9 19h6',
};
const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const byId = id => document.getElementById(id);
const names = {overview:'Обзор', twitch:'Twitch-стримеры', queue:'Очередь обработки', clips:'Готовые нарезки', settings:'Настройки'};
const selectedClips=new Set();
const state = {view:location.hash.slice(1) || 'overview', data:null, selected:null, queueFilter:'all', clipFilter:'all', query:'', logs:[], logJob:null, logFilter:'all', autoScroll:true, uploadProfile:'both', connected:false, settings:null, formDirty:false, formBusy:false, busyUpload:false, fingerprint:'', toastTimer:null};
if (!names[state.view]) state.view='overview';
let currentXHR=null;

function bytes(n) { if(!n) return '0 Б'; const units=['Б','КБ','МБ','ГБ','ТБ']; const i=Math.min(4,Math.floor(Math.log(n)/Math.log(1024))); return `${(n/1024**i).toLocaleString('ru-RU',{maximumFractionDigits:i>1?1:0})} ${units[i]}`; }
function duration(ms) {const n=Math.max(0,Math.floor((ms||0)/1000));return n>=3600?`${Math.floor(n/3600)}:${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`:`${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;}
function timeOf(ts) {return new Date(ts*1000).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function elapsed(job) {return duration(((job.finished||Date.now()/1000)-(job.started||job.created))*1000);}
function jobStatus(job) {return {queued:'В очереди',running:'В обработке',recording:'Идёт запись',done:'Готово',error:'Ошибка',cancelled:'Отменено',interrupted:'Прервано'}[job.status]||job.status;}
function badge(job) {return `<span class="badge ${['running','recording'].includes(job.status)?'running':job.status==='done'?'success':job.status==='error'?'error':job.status==='interrupted'?'warning':''}">${job.status==='recording'?'<span class="tiny-dot"></span>':''}${jobStatus(job)}</span>`;}
function streamerBadge(s) {const d=state.data; if(!s.enabled) return '<span class="badge">Пауза</span>'; if(!d.twitch.configured) return '<span class="badge warning">Не подключён</span>'; if(d.twitch.error) return '<span class="badge warning">Ошибка проверки</span>'; return s.status==='live'?'<span class="badge live"><span class="tiny-dot"></span> В эфире</span>':s.status==='offline'?'<span class="badge">Не в сети</span>':s.status==='not_found'?'<span class="badge error">Канал не найден</span>':'<span class="badge">Ожидание проверки</span>';}
function switchControl(s, field, label) {return `<button class="switch" role="switch" aria-checked="${Boolean(s[field])}" aria-label="${esc(label)} для ${esc(s.login)}" data-action="toggle-streamer" data-id="${s.id}" data-field="${field}"></button>`;}
function toast(message,error=false) {const node=byId('toast');clearTimeout(state.toastTimer);node.textContent=message;node.classList.toggle('error',error);node.hidden=false;state.toastTimer=setTimeout(()=>node.hidden=true,error?7000:4000);}

async function api(path,method='GET',body) {
  const options={method,headers:{'X-Rezak-Client':'1'}};
  if(body!==undefined) {options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}
  let response;
  try {response=await fetch('/api'+path,options);} catch {throw new Error('Нет связи с локальной службой. Запустите Rezak Studio.');}
  const data=await response.json();
  if(!response.ok) {const detail=Array.isArray(data.detail)?data.detail.map(x=>x.msg).join('; '):data.detail;throw new Error(detail||'Не удалось выполнить операцию');}
  return data;
}

function nodeKey(node) {
  if(node.nodeType!==1)return null;
  return node.id||node.dataset.logId||node.dataset.key||(node.dataset.id?node.dataset.action+':'+node.dataset.id:null)||(node.matches('.nav-item')?node.getAttribute('href'):null);
}
function patchChildren(parent, incoming) {
  let cursor=parent.firstChild;
  for(const source of [...incoming.childNodes]) {
    const key=nodeKey(source);
    let target=key?[...parent.childNodes].find(n=>nodeKey(n)===key):cursor;
    if(target&&(target.nodeType!==source.nodeType||target.nodeName!==source.nodeName||(!key&&nodeKey(target))))target=null;
    if(!target){target=source.cloneNode(true);parent.insertBefore(target,cursor);}
    else {
      if(target!==cursor)parent.insertBefore(target,cursor);
      if(target.nodeType===3){if(target.nodeValue!==source.nodeValue)target.nodeValue=source.nodeValue;}
      else if(target.nodeType===1){
        if(target.id==='log-content'){cursor=target.nextSibling;continue;}
        for(const attr of [...target.attributes])if(!source.hasAttribute(attr.name)&&attr.name!=='data-bound')target.removeAttribute(attr.name);
        for(const attr of [...source.attributes])if(target.getAttribute(attr.name)!==attr.value)target.setAttribute(attr.name,attr.value);
        if(target instanceof HTMLInputElement && target.type==='checkbox')target.checked=source.checked;
        if(target.id!=='log-content'&&target!==document.activeElement)patchChildren(target,source);
      }
    }
    cursor=target.nextSibling;
  }
  while(cursor){const next=cursor.nextSibling;cursor.remove();cursor=next;}
}
function patchHTML(node,html) {const template=document.createElement('template');template.innerHTML=html;patchChildren(node,template.content);}

function selectedJob() {const jobs=state.data.jobs;return jobs.find(j=>j.id===state.selected)||jobs.find(j=>['running','recording'].includes(j.status))||jobs[0];}
function nav() {
  const d=state.data;
  const counts={twitch:d.streamers.length,queue:d.jobs.filter(j=>['queued','running','recording'].includes(j.status)).length,clips:d.clips.length};
  patchHTML(byId('navigation'),['overview','twitch','queue','clips'].map(key=>`<a href="#${key}" class="nav-item ${state.view===key?'active':''}" ${state.view===key?'aria-current="page"':''} title="${names[key]}">${icon(key)}<span class="nav-label">${names[key]}</span>${counts[key]!==undefined?`<span class="nav-count">${counts[key]}</span>`:''}</a>`).join(''));
  patchHTML(byId('settings-nav'),icon('settings')+'<span class="nav-label">Настройки</span>');
  byId('settings-nav').classList.toggle('active',state.view==='settings');
  byId('current-page').textContent=names[state.view];
  const gpu=d.system.gpu;
  byId('gpu-summary').innerHTML=`<div class="gpu-title">${icon('chip')}<span>${gpu?esc(gpu.name):'GPU · проверка'}</span></div>${gpu?`<progress value="${gpu.used_mib}" max="${gpu.total_mib}" aria-label="Использование видеопамяти"></progress><span>${(gpu.used_mib/1024).toFixed(1)} / ${(gpu.total_mib/1024).toFixed(1)} ГБ VRAM</span>`:'<span>Нагрузка появится после проверки</span>'}`;
  byId('footer-status').textContent=d.system.docker===false?'Docker не запущен · откройте Docker Desktop':`${d.queue_paused?'Очередь на паузе':'Локальная очередь активна'} · свободно ${bytes(d.system.free_bytes)}`;
}

function heading(title,subtitle,actions='') {return `<div class="page-heading"><div><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="heading-actions">${actions}</div></div>`;}
function uploadButton() {return `<button class="button primary" aria-label="Добавить видео" data-action="upload">${icon('plus')}<span>Добавить видео</span></button>`;}
function empty(symbol,title,text,action='') {return `<div class="empty-state"><div class="empty-symbol">${icon(symbol)}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;}
function stages(job) {return `<div class="pipeline-stages ${job?'':'task-empty-stages'}">${state.data.stages.map(s=>{const info=job?.stages?.[s.id];const status=info?.status==='done'?'done':job?.status==='running'&&job.stage===s.id?'active':'';return `<div class="stage-cell ${status}" title="${esc(s.label)}${(job?.kind==='clip_edit'&&['asr','llm'].includes(s.id)||job?.kind==='clip_refine'&&s.id==='asr')?' <b>Не требуется</b>':info?' · '+Math.round(info.progress*100)+'%':''}"><div class="stage-track"></div><span>${esc(s.label)}${(job?.kind==='clip_edit'&&['asr','llm'].includes(s.id)||job?.kind==='clip_refine'&&s.id==='asr')?' <b>Не требуется</b>':info?' <b>'+Math.floor(info.progress*100)+'%</b>':''}</span></div>`;}).join('')}</div>`;}
function jobRow(job) {return `<button class="task-row ${state.selected===job.id?'selected':''}" data-action="select-job" data-id="${job.id}"><span class="file-symbol">${icon(job.kind==='capture'?'record':'file')}</span><span class="task-row-main"><span class="task-title">${esc(job.title)}</span><span class="task-meta">${badge(job)}<span>${job.kind==='capture'?'Twitch':job.profile==='both'?'9:16 + 16:9':job.profile==='vertical'?'9:16':'16:9'}</span><span>${job.metadata.duration_ms?duration(job.metadata.duration_ms):bytes(job.metadata.bytes)}</span></span>${job.status==='running'?`<progress value="${job.progress}" max="100" aria-label="Прогресс задачи"></progress>`:''}</span><span class="task-fraction">${job.status==='running'?Math.floor(job.progress)+'%':job.status==='recording'?icon('record'):icon('chevron')}</span></button>`;}
function details(job) {
  if(!job) return `<section class="panel"><div class="panel-header"><h2>Очередь обработки <span class="panel-count">0</span></h2><span class="badge">Ожидание</span></div>${empty('queue','Всё готово к первой записи','Добавьте видео с компьютера или настройте автозапись Twitch.')}${stages(null)}</section>`;
  const active=job.status==='running';const recording=job.status==='recording';
  const phase=job.stages?.[job.stage]||{};
  const action=['running','recording','queued'].includes(job.status)?`<button class="icon-button" data-action="cancel-job" data-id="${job.id}" title="Остановить задачу" aria-label="Остановить задачу">${icon('stop')}</button>`:['error','cancelled','interrupted'].includes(job.status)&&['video','clip_edit','clip_refine'].includes(job.kind)?`<button class="button ghost small" data-action="retry-job" data-id="${job.id}">${icon('refresh')}Повторить</button>`:job.exports?.length?`<button class="button ghost small" data-view="clips" aria-label="Посмотреть готовые ролики">${icon('clips')}<span>Результаты · ${job.exports.length}</span></button>`:'';
  return `<section class="panel job-detail" data-key="job-detail"><div class="active-job"><div class="active-job-top"><div class="active-job-title"><span class="file-symbol">${icon(job.kind==='capture'?'record':'file')}</span><div><h3 title="${esc(job.title)}">${esc(job.title)}</h3><p>${job.kind==='capture'?'Автозапись Twitch':job.profile==='both'?'Вертикальные ролики и горизонтальная подборка':job.profile==='vertical'?'Вертикальные ролики 9:16':'Горизонтальная подборка 16:9'} · ${job.id.slice(0,8)}</p></div></div>${action}</div><div class="progress-heading"><span>${recording?'Прямая запись эфира':active?'Прогресс по этапам':jobStatus(job)}</span><span class="progress-number">${recording?bytes(job.metadata.bytes):Math.floor(job.progress)+'<small>%</small>'}</span></div><progress ${recording?'':`value="${job.progress}"`} max="100" aria-label="${recording?'Идёт запись эфира':'Общий прогресс обработки'}"></progress><div class="active-detail"><span class="tiny-dot"></span>${esc(job.status==='queued'&&state.data.queue_paused?'Очередь на паузе':job.detail||'Ожидает обработки')}</div>${job.status==='queued'&&state.data.queue_paused?'<button class="button ghost small" data-action="pause-queue" aria-label="Продолжить очередь">Продолжить очередь</button>':''}<div class="detail-measures"><span><strong class="elapsed" data-job="${job.id}">${elapsed(job)}</strong>Прошло времени</span>${phase.processed_ms!==undefined?`<span><strong>${duration(phase.processed_ms)} / ${duration(phase.total_ms)}</strong>Обработано медиа</span>`:''}${phase.windows_total?`<span><strong>${phase.windows_done} / ${phase.windows_total}</strong>Смысловых окон</span>`:''}<span><strong>${job.metadata.duration_ms?duration(job.metadata.duration_ms):'—'}</strong>Длительность исходника</span></div></div>${job.kind==='capture'?'<div class="panel-body side-note">Части сохраняются каждые 15 минут. Нарезка работает отдельно от записи.</div>':stages(job)}${job.kind==='capture'&&['error','interrupted','done','cancelled'].includes(job.status)?`<div class="panel-body"><button class="button ghost small" data-action="recover" data-id="${job.id}">${icon('refresh')}Обработать сохранённые части</button></div>`:''}${job.error?`<div class="job-error" role="alert">${icon('info')}<span>${esc(job.error)}</span></div>`:''}</section>`;
}

function consolePanel(job) {return `<section class="console" data-key="journal-panel"><div class="console-header"><div class="console-title">${icon('terminal')}<span>${job?'Журнал обработки':'Системный журнал'}</span></div><div class="console-actions"><select id="log-filter" aria-label="Уровень журнала"><option value="all" ${state.logFilter==='all'?'selected':''}>Все события</option><option value="error" ${state.logFilter==='error'?'selected':''}>Ошибки</option></select>${job?`<a class="icon-button" href="/api/jobs/${job.id}/log" title="Скачать журнал" aria-label="Скачать журнал">${icon('download')}</a>`:''}<button class="follow-button" data-action="autoscroll" aria-pressed="${state.autoScroll}" title="${state.autoScroll?'Отключить':'Включить'} автопрокрутку" aria-label="Автопрокрутка журнала">${icon('queue')}</button></div></div><div id="log-content" class="log-content" role="log" aria-live="off" tabindex="0" aria-label="Журнал событий"></div><div class="console-footer"><span><span class="tiny-dot"></span>События от движка</span><span>${job?'Задача '+job.id.slice(0,8):'Локальная служба'}</span></div></section>`;}
function syncLogFollow() {
  const button=document.querySelector('[data-action="autoscroll"]');if(!button)return;
  button.setAttribute('aria-pressed',String(state.autoScroll));
  button.title=state.autoScroll?'Приостановить следование':'Перейти к новым событиям';
  patchHTML(button,icon(state.autoScroll?'pause':'arrow')+'<span>'+(state.autoScroll?'В реальном времени':'К новым событиям')+'</span>');
}
function renderLogs(forceFollow=false) {
  const node=byId('log-content');if(!node)return;
  const jobId=selectedJob()?.id||'',context=jobId+':'+state.logFilter;
  const logs=state.logFilter==='error'?state.logs.filter(x=>['error','warning'].includes(x.level)):state.logs;
  const oldTop=node.scrollTop,changed=node.dataset.context!==context;
  let appended=false;
  if(changed){node.replaceChildren();node.dataset.context=context;}
  node.dataset.jobId=jobId;
  if(logs.length){
    node.querySelector('.log-empty')?.remove();
    const existing=new Set([...node.children].map(n=>n.dataset.logId));
    const fragment=document.createDocumentFragment();
    for(const row of logs)if(!existing.has(String(row.id))){
      appended=true;
      const line=document.createElement('div');line.className='log-line '+row.level;line.dataset.logId=String(row.id);
      const values=[timeOf(row.at),({info:'INFO',warning:'WARN',error:'ERROR',success:'OK'})[row.level]||'INFO',row.message];
      ['log-time','log-level','log-message'].forEach((cls,i)=>{const span=document.createElement('span');span.className=cls;span.textContent=values[i];line.append(span);});fragment.append(line);
    }
    node.append(fragment);
    // Do not discard text the user is currently selecting to copy.
    if(!node.contains(window.getSelection()?.anchorNode)){
      const retained=new Set(logs.map(r=>String(r.id)));
      for(const line of [...node.children])if(!retained.has(line.dataset.logId))line.remove();
    }
  }else if(!node.firstChild){const empty=document.createElement('p');empty.className='log-empty';empty.textContent=state.logFilter==='error'?'Ошибок и предупреждений нет.':'Здесь появятся события обработки и диагностика.';node.append(empty);}
  if(state.autoScroll&&(appended||changed||forceFollow))node.scrollTo({top:node.scrollHeight,behavior:'instant'});
  else if(changed)node.scrollTo({top:0,behavior:'instant'});
  else if(node.scrollTop!==oldTop)node.scrollTo({top:oldTop,behavior:'instant'});
  syncLogFollow();
}


function twitchPanel() {
  const d=state.data;
  return `<section class="panel"><div class="panel-header"><h2 class="twitch-heading">${icon('twitch')}Twitch <span class="panel-count">${d.streamers.length}</span></h2><button class="icon-button" data-action="add-streamer" title="Добавить стримера" aria-label="Добавить стримера">${icon('plus')}</button></div>${!d.twitch.configured?'<div class="connection-note">Для отслеживания эфиров <button data-view="settings">подключите Twitch API</button>.</div>':''}${d.streamers.length?d.streamers.slice(0,4).map(s=>`<div class="watcher-row"><div class="avatar">${esc(s.display_name.slice(0,1).toUpperCase())}</div><div class="watcher-name"><strong>${esc(s.display_name)}</strong><small>${s.live_clip?'LIVE TikTok':s.auto_record?'Автозапись включена':'Только отслеживание'}</small></div>${streamerBadge(s)}</div>`).join(''):`<div class="empty-state compact"><div class="empty-symbol">${icon('twitch')}</div><h3>Ваши стримеры — здесь</h3><p>Добавьте канал. Когда начнётся эфир, студия включит запись.</p><button class="button ghost small" data-action="add-streamer">${icon('plus')}Добавить канал</button></div>`}<div class="watcher-footer"><span>${d.twitch.last_check?'Проверено '+timeOf(d.twitch.last_check):'Проверка каждые '+d.twitch.poll_interval+' с'}</span><button class="subtle-link" data-view="twitch">Все каналы ${icon('arrow')}</button></div></section>`;
}
function recentPanel() {const clips=state.data.clips.slice(0,2);return `<section class="panel"><div class="panel-header"><h2>Последние нарезки</h2><button class="subtle-link" data-view="clips">Все ${icon('arrow')}</button></div>${clips.length?clips.map(c=>`<button class="recent-clip" data-action="play" data-file="${esc(c.filename)}"><img class="clip-mini" src="/api/covers/${encodeURIComponent(c.filename)}" alt="Превью ролика" loading="lazy"><span><strong>${esc(c.title||c.source_id)}</strong><small>${c.profile==='vertical'?'9:16':'16:9'} <span>·</span> ${duration(c.duration_ms)}${c.test_fixture?' · Тестовая запись':''}</small></span><span class="play-small">${icon('play')}</span></button>`).join(''):'<div class="empty-state compact"><p>Готовые ролики появятся после первой обработки.</p></div>'}</section>`;}

function renderOverview() {
  const d=state.data,job=selectedJob();
  const active=d.jobs.filter(j=>['queued','running','recording'].includes(j.status)).length;
  return `${heading('Рабочая студия',active?`${active} задач в работе · запись и монтаж под контролем`:'Локальная студия · загрузите запись или подключите Twitch',uploadButton())}
  <div class="overview-grid"><div class="work-column">
    <section class="source-tray" data-key="source-tray"><div class="dropzone" id="dropzone" role="button" tabindex="0" aria-label="Добавить видео для обработки"><div class="drop-symbol">${icon('upload')}</div><div><h2>Добавить запись стрима</h2><p>Перетащите видео сюда или выберите файл · до 20 ГБ</p></div>${icon('plus')}</div><label class="upload-format">Экспорт<select id="upload-profile" aria-label="Формат экспорта"><option value="both" ${state.uploadProfile==='both'?'selected':''}>9:16 + 16:9</option><option value="vertical" ${state.uploadProfile==='vertical'?'selected':''}>9:16</option><option value="horizontal" ${state.uploadProfile==='horizontal'?'selected':''}>16:9</option></select></label></section>
    ${details(job)}${consolePanel(job)}</div>
    <aside class="side-column">${twitchPanel()}${recentPanel()}${d.jobs.length>1?`<section class="panel"><div class="panel-header"><h2>Другие задачи</h2><button class="subtle-link" data-view="queue">Вся очередь ${icon('arrow')}</button></div>${d.jobs.filter(j=>j.id!==job?.id).slice(0,3).map(jobRow).join('')}</section>`:''}<p class="side-note">Whisper → Bonsai2 → монтаж.<br>Перед публикацией проверьте выбранные моменты и субтитры.</p></aside></div>`;
}

function streamerRecordAction(s) {
  const capture=state.data.jobs.find(j=>j.kind==='capture'&&j.status==='recording'&&j.metadata.streamer_id===s.id);
  if(capture)return `<button class="button ghost small" data-action="cancel-job" data-id="${capture.id}" aria-label="Остановить запись ${esc(s.login)}">${icon('stop')}Стоп</button>`;
  if(s.live_clip)return `<button class="button primary small" data-action="record" data-id="${s.id}" ${!s.enabled||!s.auto_record?'disabled':''} aria-label="Запустить LIVE для ${esc(s.login)}">${icon('record')}LIVE</button>`;
  return s.status==='live'?`<button class="icon-button" data-action="record" data-id="${s.id}" aria-label="Записать эфир ${esc(s.login)}">${icon('record')}</button>`:'';
}

function renderTwitch() {
  const d=state.data;
  return `${heading('Twitch-стримеры','Запись эфиров, LIVE TikTok и обработка сохранённых частей',`<button class="button ghost" aria-label="Проверить эфиры" data-action="refresh-twitch">${icon('refresh')}<span>Проверить эфиры</span></button><button class="button primary" aria-label="Добавить стримера" data-action="add-streamer">${icon('plus')}<span>Добавить стримера</span></button>`)}${!d.twitch.configured?`<div class="notice">${icon('info')}<span>Подключите Twitch API, чтобы студия определяла начало эфира. Для ручного LIVE без API добавьте канал, включите LIVE и нажмите кнопку LIVE.</span><button class="button ghost small" data-view="settings">Подключить Twitch ${icon('arrow')}</button></div>`:d.twitch.error?`<div class="notice">${icon('info')}<span>${esc(d.twitch.error)}</span><button class="button ghost small" data-view="settings">Настройки</button></div>`:''}${d.streamers.length?`<div class="table-wrap"><table class="streamer-table"><thead><tr><th>Отслеживать / канал</th><th>Состояние</th><th>Автозапись</th><th>Нарезки</th><th>LIVE TikTok</th><th>Качество</th><th></th></tr></thead><tbody>${d.streamers.map(s=>`<tr><td><div class="identity-cell">${switchControl(s,'enabled','Отслеживать')}<div class="avatar">${esc(s.display_name[0].toUpperCase())}</div><div><strong>${esc(s.display_name)}</strong><small>${s.title?esc(s.title):'twitch.tv/'+esc(s.login)}</small></div></div></td><td>${streamerBadge(s)}${s.viewers!==null?`<small class="test-label">${s.viewers.toLocaleString('ru-RU')} зрителей</small>`:''}</td><td>${switchControl(s,'auto_record','Автозапись')}</td><td>${switchControl(s,'auto_clip','Автонарезка')}</td><td>${switchControl(s,'live_clip','LIVE TikTok во время эфира')}</td><td><select class="quality-select" data-quality="${s.id}" aria-label="Качество записи для ${esc(s.login)}">${['720p','1080p','best'].map(q=>`<option value="${q}" ${s.quality===q?'selected':''}>${q==='best'?'Лучшее':q}</option>`).join('')}</select></td><td>${streamerRecordAction(s)}<a class="icon-button" href="https://www.twitch.tv/${encodeURIComponent(s.login)}" target="_blank" rel="noopener noreferrer" title="Открыть Twitch-канал" aria-label="Открыть канал ${esc(s.login)}">${icon('external')}</a><button class="icon-button" data-action="delete-streamer" data-id="${s.id}" title="Удалить из списка; записи останутся" aria-label="Удалить стримера ${esc(s.login)}">${icon('trash')}</button></td></tr>`).join('')}</tbody></table></div><p class="side-note">Обычная запись — части по 15 минут. LIVE — непрерывная запись с сегментами около 2 минут и перекрывающимися окнами до 8 минут. Последние 2 минуты ждут развязки; скорость зависит от очереди. LIVE работает при включённой автозаписи, независимо от переключателя «Нарезки». Смена режима — после остановки записи. Сохранённые части остаются.</p>`:`<section class="panel">${empty('twitch','Кого будем записывать?','Добавьте любимых стримеров. Эфиры будут записываться, пока локальная служба запущена.',`<button class="button primary" aria-label="Добавить стримера" data-action="add-streamer">${icon('plus')}Добавить первого стримера</button>`)}</section>`}`;
}

function renderQueue() {
  const d=state.data;const filters={all:'Все задачи',active:'В работе',done:'Готово',error:'Требуют внимания'};
  const filtered=d.jobs.filter(j=>state.queueFilter==='all'||state.queueFilter==='active'&&['queued','running','recording'].includes(j.status)||state.queueFilter==='done'&&j.status==='done'||state.queueFilter==='error'&&['error','interrupted'].includes(j.status));
  const job=selectedJob();
  return `${heading('Очередь обработки',d.queue_paused?'На паузе · текущая задача продолжает работу':'Один GPU-пайплайн · запись Twitch работает независимо',`<button class="button ghost" data-action="pause-queue" aria-label="${state.data.queue_paused?'Продолжить очередь':'Пауза очереди'}">${icon(d.queue_paused?'play':'pause')}<span>${d.queue_paused?'Продолжить очередь':'Пауза очереди'}</span></button>${uploadButton()}`)}<div class="tabs-row"><div class="tabs">${Object.entries(filters).map(([key,value])=>`<button class="tab ${state.queueFilter===key?'active':''}" data-queue-filter="${key}">${value}</button>`).join('')}</div></div><div class="queue-layout"><section class="panel queue-list">${filtered.length?filtered.map(jobRow).join(''):empty('queue','Очередь пуста',state.queueFilter==='all'?'Добавьте видео, чтобы начать обработку.':'Нет задач в этом состоянии.')}</section><div class="queue-details">${details(job)}${consolePanel(job)}</div></div>`;
}

function visibleClips(){return state.data.clips.filter(c=>(state.clipFilter==='all'||c.profile===state.clipFilter)&&(c.title||c.source_id).toLowerCase().includes(state.query.toLowerCase()));}
function renderClips() {
  const clips=visibleClips();
  for(const name of selectedClips)if(!state.data.clips.some(c=>c.filename===name))selectedClips.delete(name);
  return `${heading('Готовые нарезки',`${state.data.clips.length} актуальных экспортов · исходные записи сохранены`,`<button class="button ghost" aria-label="Папка результатов" data-action="open-exports">${icon('folder')}<span>Папка результатов</span></button>${uploadButton()}`)}<div class="tabs-row"><div class="tabs">${[['all','Все форматы'],['vertical','Вертикальные 9:16'],['horizontal','Подборки 16:9']].map(([key,label])=>`<button class="tab ${state.clipFilter===key?'active':''}" data-clip-filter="${key}">${label}</button>`).join('')}</div><input class="search" id="clip-search" placeholder="Поиск по источнику" aria-label="Поиск нарезок" value="${esc(state.query)}"></div><div class="clip-selection" role="group" aria-label="Выбор роликов"><button class="button ghost small" data-action="select-visible-clips">Выбрать видимые (${clips.length})</button><span aria-live="polite">Выбрано: ${selectedClips.size}</span><button class="button ghost small" data-action="clear-selected-clips" ${selectedClips.size?'':'disabled'}>Снять выбор</button><button class="button danger small" data-action="delete-selected-clips" ${selectedClips.size?'':'disabled'}>Удалить выбранные</button></div>${clips.length?`<div class="clip-grid">${clips.map(c=>`<article class="clip-card ${selectedClips.has(c.filename)?'is-selected':''}" data-key="${esc(c.filename)}"><label class="clip-select"><input type="checkbox" data-select-clip="${esc(c.filename)}" ${selectedClips.has(c.filename)?'checked':''} aria-label="Выбрать ${esc(c.title||c.source_id)}"><span>Выбрать</span></label><button class="clip-preview" data-action="play" data-file="${esc(c.filename)}" aria-label="Смотреть ${esc(c.title||c.source_id)}"><img src="/api/covers/${encodeURIComponent(c.filename)}" loading="lazy" alt="Кадр из ${esc(c.title||c.source_id)}"><span class="clip-play">${icon('play')}</span><span class="clip-labels"><span>${c.profile==='vertical'?'9:16':'16:9'}</span><span>${duration(c.duration_ms)}</span></span></button><div class="clip-card-body"><h2 class="clip-card-title">${esc(c.title||c.source_id)}</h2><div class="clip-card-meta"><span>${c.width} × ${c.height} · ${bytes(c.bytes)}</span><a href="/api/clips/${encodeURIComponent(c.filename)}?download=true" class="icon-button" title="Скачать ролик" aria-label="Скачать ${esc(c.title||c.source_id)}">${icon('download')}</a></div><div class="clip-actions"><button class="button ghost small" data-action="edit-clip" data-file="${esc(c.filename)}" aria-label="Редактировать ${esc(c.title||c.source_id)}">${icon('settings')}Редактировать</button><button class="icon-button delete-clip" data-action="delete-clip" data-file="${esc(c.filename)}" aria-label="Удалить ${esc(c.title||c.source_id)}" title="Удалить нарезку">${icon('trash')}</button></div>${c.test_fixture?'<span class="test-label">Синтетическая тестовая запись</span>':''}</div></article>`).join('')}</div>`:`<section class="panel">${empty('clips','Пока нет роликов',state.query?'Попробуйте другое название источника.':'Добавьте запись. После обработки здесь появятся готовые нарезки.',uploadButton())}</section>`}`;
}

function renderSettings() {
  const s=state.settings||{};const d=state.data;
  return `${heading('Настройки','Подключение Twitch и локального движка')}<div class="settings-grid"><section class="panel"><div class="panel-header"><h2>Twitch API</h2><span class="badge ${d.twitch.configured?'success':''}">${d.twitch.configured?'Ключи сохранены':'Не подключён'}</span></div><form id="settings-form" class="settings-form"><p>Создайте приложение в <a href="https://dev.twitch.tv/console/apps" target="_blank" rel="noopener noreferrer">консоли разработчика Twitch ${icon('external')}</a> и скопируйте его ключи. Они нужны для определения начала эфиров.</p><label class="field">Client ID<input name="client_id" required autocomplete="off" spellcheck="false" value="${esc(s.client_id||'')}" placeholder="Client ID приложения Twitch"></label><label class="field">Client Secret<input name="client_secret" type="password" autocomplete="new-password" placeholder="${s.secret_saved?'Сохранён · оставьте пустым, чтобы не менять':'Client Secret приложения Twitch'}"><small>Секрет шифруется Windows DPAPI для вашей учётной записи. В журнал и Git он не попадает.</small></label><label class="field">Проверять эфиры<select name="poll_interval">${[30,60,120,300].map(n=>`<option value="${n}" ${s.poll_interval===n?'selected':''}>${n<60?'Каждые '+n+' секунд':'Каждые '+n/60+' мин.'}</option>`).join('')}</select></label><p class="form-error" id="settings-error" role="alert" hidden></p><button class="button primary" type="submit">Сохранить и проверить ${icon('arrow')}</button><p class="form-success" id="settings-success" role="status" hidden></p></form></section><div class="settings-stack"><section class="panel"><div class="panel-header"><h2>Локальный движок</h2>${d.system.docker?'<span class="badge success">Docker доступен</span>':'<span class="badge warning">Проверка Docker</span>'}</div><div class="settings-info"><div class="kv-row"><span>Распознавание</span><strong>Whisper small · int8_float16</strong></div><div class="kv-row"><span>Отбор моментов</span><strong>Bonsai2 27B · PTQ1_0</strong></div><div class="kv-row"><span>Графический процессор</span><strong>${d.system.gpu?esc(d.system.gpu.name):'Ожидание проверки'}</strong></div><div class="kv-row"><span>Модель Bonsai</span><strong>${d.system.model==='running'?'Контейнер запущен':'Запускается для обработки'}</strong></div><div class="kv-row"><span>Порядок работы</span><strong>ASR → освобождение GPU → Bonsai2 → монтаж</strong></div></div><p class="settings-note">Первый запуск Bonsai может занять несколько минут. Его загрузка отображается отдельным этапом без выдуманного процента.</p></section><section class="panel"><div class="panel-header"><h2>Хранилище</h2></div><div class="settings-info"><div class="kv-row"><span>Свободно на диске</span><strong>${bytes(d.system.free_bytes)}</strong></div><div class="kv-row"><span>Максимальный файл</span><strong>20 ГБ</strong></div><div class="kv-row"><span>Исходники и экспорт</span><strong>${esc(s.data_directory||'Загрузка…')}</strong></div><div class="kv-row"><span>База и журналы</span><strong>SQLite · на этом компьютере</strong></div></div><p class="settings-note">Исходники не удаляются автоматически. Загрузка нового оформления не запускает распознавание заново.</p></section></div></div><div class="settings-end"><span>Закрытие окна не останавливает локальную службу и автозапись.</span><button class="button ghost" data-action="shutdown">${icon('stop')}Завершить работу студии</button></div>`;
}

function render() {
  if(!state.data)return;
  document.body.dataset.view=state.view;nav();
  const scrollTop=byId('log-content')?.scrollTop||0;
  const renderers={overview:renderOverview,twitch:renderTwitch,queue:renderQueue,clips:renderClips,settings:renderSettings};
  patchHTML(byId('main'),renderers[state.view]());
  const journal=byId('log-content');if(journal&&!state.autoScroll&&journal.scrollTop!==scrollTop)journal.scrollTo({top:scrollTop,behavior:'instant'});
  setupDropzone();renderLogs();
}

function setupDropzone() {const node=byId('dropzone');if(!node||node.dataset.bound)return;node.dataset.bound='1';node.addEventListener('click',()=>byId('file-input').click());node.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();byId('file-input').click();}});['dragenter','dragover'].forEach(name=>node.addEventListener(name,e=>{e.preventDefault();node.classList.add('dragging');}));node.addEventListener('dragleave',()=>node.classList.remove('dragging'));node.addEventListener('drop',e=>{e.preventDefault();node.classList.remove('dragging');uploadFiles(e.dataTransfer.files);});}

async function refresh(force=false) {
  try {
    const data=await api('/status');
    const fingerprint=JSON.stringify(state.view==='clips'?[data.clips]:state.view==='twitch'?[data.streamers,data.twitch]:state.view==='settings'?[data.twitch,data.system]:[data.jobs,data.streamers,data.clips,data.queue_paused,data.twitch,data.system]);
    const changed=state.fingerprint!==fingerprint;state.fingerprint=fingerprint;state.data=data;state.connected=true;
    byId('connection').className='connection ready';byId('connection').innerHTML='<span class="tiny-dot"></span> Служба работает';
    const focused=byId('main').contains(document.activeElement)&&['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName);
    if(force||changed&&!focused&&!(state.view==='settings'&&(state.formDirty||state.formBusy)))render();else nav();
    const job=['overview','queue'].includes(state.view)?selectedJob():null;
    const jobId=job?.id||null;
    if(state.logJob!==jobId){state.logJob=jobId;state.logs=[];}
    if(['overview','queue'].includes(state.view)) {
      const rows=await api('/logs?'+new URLSearchParams({...(jobId?{job_id:jobId}:{}),after:state.logs.at(-1)?.id||0}));
      if(rows.length){state.logs=[...state.logs,...rows].slice(-500);renderLogs();}
    }
    document.querySelectorAll('.elapsed').forEach(node=>{const j=data.jobs.find(j=>j.id===node.dataset.job);if(j)node.textContent=elapsed(j);});
  } catch(err) {
    state.connected=false;byId('connection').className='connection error';byId('connection').innerHTML='<span class="tiny-dot"></span> Нет связи';
    byId('footer-status').textContent=err.message;
    if(!state.data)byId('main').innerHTML=`${heading('Студия недоступна','Не удалось подключиться к локальной службе')}<section class="panel">${empty('info','Проверьте локальную службу','Запустите scripts/start-studio.ps1. Эта страница подключится автоматически, когда служба станет доступна.')}</section>`;
  }
}

async function navigate(view) {if(!names[view])return;state.view=view;state.formDirty=false;location.hash=view;state.logJob=null;state.logs=[];if(view==='settings')state.settings=await api('/settings');render();await refresh(true);}

async function uploadFiles(files) {
  if(state.busyUpload)return toast('Дождитесь завершения текущей загрузки',true);
  const list=Array.from(files||[]);if(!list.length)return;
  state.busyUpload=true;const status=byId('upload-status');status.hidden=false;
  for(let i=0;i<list.length;i++) {
    const file=list[i];if(file.size>20*1024**3){toast('Файл '+file.name+' превышает 20 ГБ',true);continue;}
    status.innerHTML=`<div class="upload-status-top"><span>Добавление видео · ${i+1}/${list.length}</span><button class="icon-button" data-action="cancel-upload" title="Отменить загрузку" aria-label="Отменить загрузку">${icon('close')}</button></div><progress value="0" max="100" aria-label="Загрузка файла"></progress><p>${esc(file.name)} · ${bytes(file.size)}</p>`;
    try {
      const job=await new Promise((resolve,reject)=>{
        const xhr=new XMLHttpRequest();currentXHR=xhr;xhr.open('POST','/api/uploads');xhr.setRequestHeader('X-Rezak-Client','1');
        xhr.upload.onprogress=e=>{if(e.lengthComputable){const progress=status.querySelector('progress');if(progress)progress.value=e.loaded/e.total*100;}};
        xhr.onload=()=>{try {const result=JSON.parse(xhr.responseText);xhr.status<300?resolve(result):reject(new Error(result.detail||'Ошибка загрузки'));}catch{reject(new Error('Некорректный ответ сервера'));}};
        xhr.onerror=()=>reject(new Error('Соединение прервалось. Проверьте локальную службу.'));xhr.onabort=()=>reject(new Error('Загрузка отменена'));
        const form=new FormData();form.append('file',file);form.append('profile',state.uploadProfile);xhr.send(form);
      });
      state.selected=job.id;toast('Видео добавлено в очередь');await refresh(true);
    }catch(err){toast(err.message,true);if(err.message==='Загрузка отменена')break;}
  }
  currentXHR=null;state.busyUpload=false;status.hidden=true;byId('file-input').value='';
}

function play(filename) {const clip=state.data.clips.find(c=>c.filename===filename);if(!clip)return;byId('player-title').textContent=clip.title||clip.source_id;byId('player-meta').textContent=`${clip.width} × ${clip.height} · ${duration(clip.duration_ms)} · ${bytes(clip.bytes)}`;byId('player').src='/api/clips/'+encodeURIComponent(filename);byId('player-download').href='/api/clips/'+encodeURIComponent(filename)+'?download=true';byId('player-dialog').showModal();byId('player').play().catch(()=>{});}

document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action],button[data-view],a[data-view],[data-close],[data-queue-filter],[data-clip-filter]');if(!target)return;
  try {
    if(target.dataset.close){byId(target.dataset.close).close();return;}
    if(target.dataset.view){await navigate(target.dataset.view);return;}
    if(target.dataset.queueFilter){state.queueFilter=target.dataset.queueFilter;render();return;}
    if(target.dataset.clipFilter){state.clipFilter=target.dataset.clipFilter;render();return;}
    const action=target.dataset.action,id=target.dataset.id;
    if(action==='upload')byId('file-input').click();
    else if(action==='cancel-upload')currentXHR?.abort();
    else if(action==='add-streamer'){byId('streamer-error').hidden=true;byId('streamer-dialog').showModal();byId('streamer-login').focus();}
    else if(action==='select-job'){state.selected=id;state.logJob=null;state.logs=[];render();await refresh(true);}
    else if(action==='pause-queue'){await api('/queue','POST',{paused:!state.data.queue_paused});await refresh(true);}
    else if(action==='cancel-job'){await api('/jobs/'+id+'/cancel','POST');toast('Остановка запрошена. Сохранённые файлы останутся.');await refresh(true);}
    else if(action==='retry-job'){await api('/jobs/'+id+'/retry','POST');toast('Задача возвращена в очередь');await refresh(true);}
    else if(action==='recover'){const r=await api('/jobs/'+id+'/recover','POST');toast('Добавлено частей: '+r.jobs.length);await refresh(true);}
    else if(action==='delete-streamer'){await api('/streamers/'+id,'DELETE');toast('Канал удалён из списка. Записи сохранены.');await refresh(true);}
    else if(action==='toggle-streamer'){const s=state.data.streamers.find(s=>s.id===id);await api('/streamers/'+id,'PATCH',{[target.dataset.field]:!s[target.dataset.field]});await refresh(true);}
    else if(action==='refresh-twitch'){const r=await api('/twitch/refresh','POST');toast(r.configured?'Проверка эфиров запрошена':'Сначала подключите Twitch в настройках',!r.configured);}
    else if(action==='record'){const j=await api('/streamers/'+id+'/record','POST');state.selected=j.id;await navigate('queue');}
    else if(action==='edit-clip')openClipEditor(target.dataset.file);
    else if(action==='select-visible-clips'){for(const clip of visibleClips())selectedClips.add(clip.filename);render();}
    else if(action==='clear-selected-clips'){selectedClips.clear();render();}
    else if(action==='delete-selected-clips')confirmClipDelete([...selectedClips]);
    else if(action==='delete-clip')confirmClipDelete(target.dataset.file);
    else if(action==='restore-clip'){await api('/trash/'+state.trashToken+'/restore','POST');state.trashToken=null;byId('clip-undo').hidden=true;await refresh(true);toast('Нарезка восстановлена');}
    else if(action==='play')play(target.dataset.file);
    else if(action==='autoscroll'){state.autoScroll=!state.autoScroll;target.setAttribute('aria-pressed',state.autoScroll);if(state.autoScroll)renderLogs(true);syncLogFollow();toast(state.autoScroll?'Автопрокрутка включена':'Автопрокрутка отключена');}
    else if(action==='open-exports'){await api('/open-exports','POST');}
    else if(action==='shutdown')byId('shutdown-dialog').showModal();
  }catch(err){toast(err.message,true);}
});

document.addEventListener('change',async event=>{
  const node=event.target;
  if(node.dataset.selectClip){if(node.checked)selectedClips.add(node.dataset.selectClip);else selectedClips.delete(node.dataset.selectClip);render();}
  if(node.id==='file-input')uploadFiles(node.files);
  if(node.id==='upload-profile')state.uploadProfile=node.value;
  if(node.id==='log-filter'){state.logFilter=node.value;renderLogs();}
  if(node.dataset.quality){try{await api('/streamers/'+node.dataset.quality,'PATCH',{quality:node.value});await refresh(true);}catch(err){toast(err.message,true);}}
});
document.addEventListener('input',event=>{if(event.target.closest('#settings-form'))state.formDirty=true;if(event.target.id==='clip-search'){const start=event.target.selectionStart;state.query=event.target.value;render();const node=byId('clip-search');node.focus();node.setSelectionRange(start,start);}});
document.addEventListener('submit',async event=>{
  if(!['streamer-form','settings-form'].includes(event.target.id))return;
  event.preventDefault();state.formBusy=true;const form=event.target;const button=form.querySelector('[type=submit]');button.disabled=true;
  if(form.id==='streamer-form'){
    byId('streamer-error').hidden=true;const data=new FormData(form);
    try{await api('/streamers','POST',{login:data.get('login'),quality:data.get('quality'),auto_record:data.has('auto_record'),auto_clip:data.has('auto_clip'),live_clip:data.has('live_clip')});byId('streamer-dialog').close();form.reset();toast('Стример добавлен');await refresh(true);}catch(err){byId('streamer-error').textContent=err.message;byId('streamer-error').hidden=false;}
  }else{
    byId('settings-error').hidden=true;byId('settings-success').hidden=true;const data=new FormData(form);
    try{await api('/settings','POST',{client_id:data.get('client_id'),client_secret:data.get('client_secret'),poll_interval:Number(data.get('poll_interval')),verify:true});form.elements.client_secret.value='';state.settings=await api('/settings');state.formDirty=false;await refresh(true);byId('settings-success').textContent='Подключение проверено. Мониторинг готов к работе.';byId('settings-success').hidden=false;}catch(err){byId('settings-error').textContent=err.message;byId('settings-error').hidden=false;}
  }
  button.disabled=false;state.formBusy=false;
});
byId('player-dialog').addEventListener('close',()=>{byId('player').pause();byId('player').removeAttribute('src');byId('player').load();});
byId('confirm-shutdown').addEventListener('click',async()=>{try{await api('/shutdown','POST');byId('shutdown-dialog').close();toast('Студия завершает работу. Записи сохраняются.');}catch(err){toast(err.message,true);}});
document.querySelectorAll('[data-close]').forEach(button=>{if(!button.innerHTML)button.innerHTML=icon('close');});
window.addEventListener('hashchange',()=>{const view=location.hash.slice(1);if(names[view]&&view!==state.view)navigate(view);});
window.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
window.addEventListener('drop',event=>{if(!event.target.closest('#dropzone')&&event.dataTransfer.types.includes('Files'))event.preventDefault();});
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='o'){event.preventDefault();byId('file-input').click();}});
async function boot(){if(state.view==='settings'){try{state.settings=await api('/settings');}catch{}}await refresh(true);setInterval(()=>refresh(),1500);}
boot();

document.addEventListener("error",event=>{if(event.target instanceof HTMLImageElement){event.target.hidden=true;event.target.parentElement.classList.add("preview-unavailable");}},true);

// Follow new events only while the reader remains at the end of the journal.
document.addEventListener('scroll',event=>{
  const node=event.target;if(node.id!=='log-content')return;
  state.autoScroll=node.scrollHeight-node.clientHeight-node.scrollTop<24;
  const button=document.querySelector('[data-action="autoscroll"]');
  if(button)syncLogFollow();
},true);

let editingClip=null,deletingClips=[];
function openClipEditor(filename){
  const clip=state.data.clips.find(c=>c.filename===filename);if(!clip)return;
  editingClip=clip;const form=byId('clip-edit-form');form.elements.title.value=clip.title||clip.source_id;form.elements.instruction.value='';
  const total=clip.editable_duration_ms||clip.duration_ms;
  form.elements.start.value='0.000';form.elements.end.value=(total/1000).toFixed(3);
  for(const field of [form.elements.start,form.elements.end]){field.max=(total/1000).toFixed(3);}
  byId('clip-edit-error').hidden=true;byId('clip-edit-player').poster='/api/covers/'+encodeURIComponent(filename);byId('clip-edit-player').src='/api/clips/'+encodeURIComponent(filename);
  byId('clip-edit-dialog').showModal();form.elements.title.focus();updateClipInterval();initFraming(clip);
}
function updateClipInterval(){
 const form=byId('clip-edit-form'),start=Number(form.elements.start.value),end=Number(form.elements.end.value);
 byId('clip-edit-duration').textContent=Number.isFinite(start)&&Number.isFinite(end)&&end>start?'Выбрано '+(end-start).toFixed(3)+' с':'Укажите корректные границы';
}
function confirmClipDelete(filenames){
 const names=Array.isArray(filenames)?filenames:[filenames];
 deletingClips=state.data.clips.filter(c=>names.includes(c.filename));if(!deletingClips.length)return;
 byId('clip-delete-title').textContent=`Удалить ролики (${deletingClips.length})?`;
 byId('confirm-clip-delete').textContent=`Удалить (${deletingClips.length})`;
 byId('clip-delete-name').textContent=deletingClips.slice(0,5).map(c=>c.title||c.source_id).join(' · ')+(deletingClips.length>5?' …':'');byId('clip-delete-error').hidden=true;
 byId('clip-delete-dialog').showModal();
}
byId('clip-edit-form').addEventListener('input',updateClipInterval);
for(const [id,field] of [['clip-set-start','start'],['clip-set-end','end']])byId(id).addEventListener('click',()=>{
 byId('clip-edit-form').elements[field].value=byId('clip-edit-player').currentTime.toFixed(3);updateClipInterval();
});
byId('clip-preview-range').addEventListener('click',()=>{const video=byId('clip-edit-player');video.currentTime=Number(byId('clip-edit-form').elements.start.value);video.play().catch(()=>{});});
byId('clip-edit-player').addEventListener('timeupdate',()=>{const video=byId('clip-edit-player');if(video.currentTime>=Number(byId('clip-edit-form').elements.end.value))video.pause();});
byId('clip-edit-dialog').addEventListener('close',()=>{const video=byId('clip-edit-player');video.pause();video.removeAttribute('src');video.load();});
byId('clip-edit-form').addEventListener('submit',async event=>{
 event.preventDefault();if(!editingClip)return;
 const form=event.target,button=form.querySelector('[type="submit"]'),error=byId('clip-edit-error');error.hidden=true;
 const instruction=form.elements.instruction.value.trim();
 const start=Math.round(Number(form.elements.start.value)*1000),end=Math.round(Number(form.elements.end.value)*1000),total=editingClip.editable_duration_ms||editingClip.duration_ms;
 if(!instruction&&(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end>total||end-start<250)){error.textContent='Выберите интервал от 0,25 с в пределах ролика.';error.hidden=false;return;}
 button.disabled=true;let queuedJob=false;
 try{
  const title=form.elements.title.value.trim();if(!title)throw new Error('Укажите название');
  if(form.elements.framing.value!=='keep'){if(instruction)throw new Error('Сохраните кадрирование отдельно от задания по речи');const mode=form.elements.framing.value;const job=await api('/clips/'+editingClip.filename+'/framing','POST',{title,mode,focus:form.elements.focus.value,region:['crop','split'].includes(mode)?readRegion('primary'):null,secondary_region:mode==='split'?readRegion('secondary'):null});state.selected=job.id;queuedJob=true;toast('Кадрирование добавлено в очередь');}
  else if(instruction){const job=await api('/clips/'+editingClip.filename+'/refine','POST',{title,instruction});state.selected=job.id;queuedJob=true;toast('Доработка по вашему заданию добавлена в очередь');}
  else if(start===0&&end===total){await api('/clips/'+editingClip.filename,'PATCH',{title});toast('Название сохранено');}
  else{const job=await api('/clips/'+editingClip.filename+'/trim','POST',{title,start_ms:start,end_ms:end});state.selected=job.id;queuedJob=true;toast('Монтаж копии добавлен в очередь');}
  byId('clip-edit-dialog').close();if(queuedJob)await navigate('queue');else await refresh(true);
 }catch(err){error.textContent=err.message;error.hidden=false;}finally{button.disabled=false;}
});
byId('confirm-clip-delete').addEventListener('click',async()=>{
 if(!deletingClips.length)return;const button=byId('confirm-clip-delete');button.disabled=true;
 try{const result=await api('/clips/delete-many','POST',{filenames:deletingClips.map(c=>c.filename)});state.trashToken=result.token;for(const c of deletingClips)selectedClips.delete(c.filename);byId('clip-delete-dialog').close();byId('clip-undo').hidden=false;await refresh(true);toast('Нарезка перемещена в корзину');}
 catch(err){byId('clip-delete-error').textContent=err.message;byId('clip-delete-error').hidden=false;}finally{button.disabled=false;}
});

byId('dismiss-clip-undo').innerHTML=icon('close');byId('dismiss-clip-undo').addEventListener('click',()=>byId('clip-undo').hidden=true);

function readRegion(name){const f=byId('clip-edit-form');return Object.fromEntries(['x','y','w','h'].map(k=>[k,Number(f.elements[name+'_'+k].value)/100]));}
function drawRegions(){for(const name of ['primary','secondary']){const r=readRegion(name),box=byId(name+'-box');box.style.left=r.x*100+'%';box.style.top=r.y*100+'%';box.style.width=r.w*100+'%';box.style.height=r.h*100+'%';}byId('secondary-box').hidden=byId('clip-edit-form').elements.framing.value!=='split';}
async function initFraming(clip){
 const f=byId('clip-edit-form');f.elements.framing.value='keep';byId('clip-framing').hidden=clip.profile!=='vertical';byId('clip-framing').open=false;if(clip.profile!=='vertical')return;byId('framing-note').textContent='Загрузка параметров…';
 for(const name of ['primary','secondary'])for(const k of ['x','y','w','h'])f.elements[name+'_'+k].value=['w','h'].includes(k)?100:0;
 byId('framing-source').src='/api/clips/'+encodeURIComponent(clip.filename)+'/source-frame';drawRegions();
 try{const plan=await api('/clips/'+clip.filename+'/framing');if(editingClip!==clip)return;const cut=plan.segments[0];for(const [name,r] of [['primary',cut.region],['secondary',cut.secondary_region]])if(r)for(const k of ['x','y','w','h'])f.elements[name+'_'+k].value=(r[k]*100).toFixed(1);byId('framing-note').textContent=cut.framing_note||'Текущий режим: '+(cut.framing||'fit');drawRegions();}catch(e){byId('framing-note').textContent=e.message;}
}
byId('clip-framing').addEventListener('input',drawRegions);
let regionDrag=null;
const framingSurface=document.querySelector('.source-framing');
framingSurface.addEventListener('pointerdown',event=>{if(event.button!==0)return;const rect=framingSurface.getBoundingClientRect();regionDrag={x:Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y:Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height)),name:byId('region-target').value};framingSurface.setPointerCapture(event.pointerId);event.preventDefault();});
framingSurface.addEventListener('pointermove',event=>{if(!regionDrag)return;const rect=framingSurface.getBoundingClientRect(),x=Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height)),r={x:Math.min(x,regionDrag.x),y:Math.min(y,regionDrag.y),w:Math.abs(x-regionDrag.x),h:Math.abs(y-regionDrag.y)},f=byId('clip-edit-form');for(const k of ['x','y','w','h'])f.elements[regionDrag.name+'_'+k].value=(r[k]*100).toFixed(1);if(f.elements.framing.value==='keep')f.elements.framing.value='crop';drawRegions();});
framingSurface.addEventListener('pointerup',()=>regionDrag=null);framingSurface.addEventListener('pointercancel',()=>regionDrag=null);
