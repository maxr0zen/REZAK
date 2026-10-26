const {chromium}=require('playwright');const assert=require('node:assert/strict');const fs=require('fs');const path=require('path');
const directory=path.resolve('.impeccable/workstation');fs.mkdirSync(directory,{recursive:true});
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const report={sizes:[],interaction:{},mocks:[],errors:[]};
 try{
 const page=await browser.newPage({viewport:{width:1440,height:900}});page.on('pageerror',e=>report.errors.push(String(e)));
 await page.goto('http://127.0.0.1:8765',{waitUntil:'networkidle'});await page.waitForSelector('#log-content .log-line');await page.evaluate(()=>document.fonts.ready);
 for(const [width,height] of [[1280,800],[1440,900],[1920,1080],[430,932]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>render());await page.waitForTimeout(100);
  const metrics=await page.evaluate(()=>{const main=byId('main'),log=byId('log-content'),r=log.getBoundingClientRect();return{width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth,mainOverflow:main.scrollHeight-main.clientHeight,logTop:r.top,logBottom:r.bottom,logHeight:r.height,mainBottom:main.getBoundingClientRect().bottom};});
  assert(metrics.scrollWidth<=width);if(width>=1280){assert(metrics.mainOverflow<=2,JSON.stringify(metrics));assert(metrics.logBottom<=metrics.mainBottom);assert(metrics.logHeight>=140);}report.sizes.push(metrics);
  await page.screenshot({path:path.join(directory,`overview-${width}.png`),fullPage:width<1000});
 }
 await page.setViewportSize({width:1440,height:900});
 report.interaction=await page.evaluate(async()=>{
  state.autoScroll=false;const log=byId('log-content');log.scrollTop=70;
  const text=log.querySelector('.log-message').firstChild;const range=document.createRange();range.setStart(text,0);range.setEnd(text,Math.min(8,text.length));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);const selected=selection.toString();const row=log.firstChild;
  const button=document.querySelector('[data-action="autoscroll"]');button.focus();
  const before=log.scrollTop;await refresh(true);
  const preserved={log:log===byId('log-content'),row:row===log.firstChild,selection:window.getSelection().toString()===selected,focus:document.activeElement===button,scroll:log.scrollTop===before};
  const original=state.logs;state.logs=[...original,{id:999999,at:Date.now()/1000,level:'warning',message:'Mock UI-only warning for filter verification'}];renderLogs();
  const appendedSelection=window.getSelection().toString()===selected;state.logFilter='error';renderLogs();const filtered=[...log.querySelectorAll('.log-line')].every(n=>n.classList.contains('warning')||n.classList.contains('error'));
  state.logFilter='all';state.logs=original;window.getSelection().removeAllRanges();renderLogs();state.autoScroll=true;renderLogs();
  return {...preserved,appendedSelection,filtered};
 });
 assert(Object.values(report.interaction).every(Boolean),JSON.stringify(report.interaction));
 await page.evaluate(()=>navigate('settings'));await page.getByLabel('Client ID',{exact:true}).fill('unsaved-value');await page.waitForTimeout(1800);assert.equal(await page.getByLabel('Client ID',{exact:true}).inputValue(),'unsaved-value');report.settingsRetained=true;
 await page.evaluate(()=>navigate('clips'));await page.locator('#clip-search').fill('Проверка');assert(await page.locator('.clip-card').count()>0);await page.locator('#clip-search').fill('');await page.locator('[data-action="play"]').first().click();await page.waitForFunction(()=>byId('player').readyState>=2);await page.keyboard.press('Escape');report.playback=true;
 await page.evaluate(()=>{document.querySelectorAll('.clip-preview img').forEach(i=>i.loading='eager')});await page.waitForFunction(()=>[...document.querySelectorAll('.clip-preview img')].every(i=>i.complete&&i.naturalWidth>0));await page.screenshot({path:path.join(directory,'clips.png'),fullPage:true});
 const beforeUpload=await(await page.request.get('http://127.0.0.1:8765/api/status')).json();
 let uploaded;
 const headers={'X-Rezak-Client':'1'};
 try{
   await page.request.post('http://127.0.0.1:8765/api/queue',{headers,data:{paused:true}});
   await page.evaluate(()=>navigate('overview'));
   const response=page.waitForResponse(r=>r.url().endsWith('/api/uploads')&&r.request().method()==='POST');
   await page.locator('#file-input').setInputFiles({name:'UI regression — загрузка и отмена.mp4',mimeType:'video/mp4',buffer:fs.readFileSync('data/sources/synthetic.mp4')});
   uploaded=await(await response).json();assert.equal(uploaded.status,'queued');
   await page.waitForFunction(id=>state.selected===id&&state.data.jobs.find(j=>j.id===id)?.status==='queued',uploaded.id);
   await page.getByRole('button',{name:'Остановить задачу',exact:true}).click();
   await page.waitForFunction(id=>state.data.jobs.find(j=>j.id===id)?.status==='cancelled',uploaded.id);
   await page.getByRole('button',{name:'Повторить',exact:true}).click();
   await page.waitForFunction(id=>state.data.jobs.find(j=>j.id===id)?.status==='queued',uploaded.id);
   await page.getByRole('button',{name:'Остановить задачу',exact:true}).click();
   await page.waitForFunction(id=>state.data.jobs.find(j=>j.id===id)?.status==='cancelled',uploaded.id);
   report.uploadCancelRetry=true;
 }finally{
   if(uploaded)await page.request.post('http://127.0.0.1:8765/api/jobs/'+uploaded.id+'/cancel',{headers});
   await page.request.post('http://127.0.0.1:8765/api/queue',{headers,data:{paused:beforeUpload.queue_paused}});
 }
 const baseline=await(await page.request.get('http://127.0.0.1:8765/api/status')).json();
 const mock=await browser.newPage({viewport:{width:1280,height:800}});
 for(const kind of ['running','error','empty','long-title']){
  const data=JSON.parse(JSON.stringify(baseline));data.streamers=[];
  if(kind==='empty'){data.jobs=[];data.clips=[];}else{data.jobs=[data.jobs.find(j=>j.status==='done')||data.jobs[0]];const j=data.jobs[0];if(kind==='running'){j.status='running';j.progress=43;j.stage='llm';j.detail='MOCK: загрузка Bonsai2, точный процент неизвестен';j.exports=[];}if(kind==='error'){j.status='error';j.error='MOCK: недостаточно памяти GPU. Закройте другие приложения и повторите задачу.';j.detail='Обработка остановлена';}if(kind==='long-title'){j.title='MOCK — '+('Очень длинное название записи стрима без сокращений '.repeat(7));}}
  await mock.route('**/api/status',route=>route.fulfill({json:data}));await mock.route('**/api/logs?*',route=>route.fulfill({json:[]}));await mock.goto('http://127.0.0.1:8765',{waitUntil:'networkidle'});await mock.waitForSelector('.overview-grid');
  const size=await mock.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,main:byId('main').scrollHeight-byId('main').clientHeight}));assert(size.scroll<=size.width);report.mocks.push({kind,...size});await mock.screenshot({path:path.join(directory,`mock-${kind}.png`)});await mock.unrouteAll();
 }
 await mock.close();await page.evaluate(()=>navigate('overview'));
 console.log(JSON.stringify(report,null,2));fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));assert.deepEqual(report.errors,[]);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
