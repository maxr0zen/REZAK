const {chromium}=require('playwright');
const fs=require('fs');
const path=require('path');
async function main(){
  const browser=await chromium.launch({headless:true,executablePath:process.env.REZAK_BROWSER||'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
  const page=await browser.newPage({viewport:{width:1440,height:960},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',err=>errors.push(String(err)));page.on('console',msg=>{if(msg.type()==='error')errors.push(msg.text());});
  const dir=path.resolve('.impeccable/review');fs.mkdirSync(dir,{recursive:true});
  await page.goto('http://127.0.0.1:8765',{waitUntil:'networkidle'});
  await page.evaluate(()=>document.fonts.ready);
  await page.getByRole('heading',{name:'Рабочая студия'}).waitFor();
  await page.evaluate(async()=>{const d=await(await fetch('/api/status')).json();for(const s of d.streamers.filter(s=>s.login==='rezak_ui_test'))await fetch('/api/streamers/'+s.id,{method:'DELETE',headers:{'X-Rezak-Client':'1'}});});
  await page.screenshot({path:path.join(dir,'desktop.png'),fullPage:true});
  const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,font:document.fonts.check('14px Inter','Привет'),heading:document.querySelector('h1').getBoundingClientRect().toJSON()}));
  await page.getByRole('link',{name:/Twitch-стримеры/}).click();
  await page.getByRole('heading',{name:'Twitch-стримеры'}).waitFor();
  await page.getByRole('button',{name:'Добавить стримера',exact:true}).first().click();
  await page.getByLabel('Канал Twitch').fill('https://twitch.tv/rezak_ui_test');
  await page.locator('#streamer-form').getByRole('button',{name:'Добавить стримера',exact:true}).click();
  await page.getByRole('cell',{name:/rezak_ui_test/}).first().waitFor();
  await page.getByRole('switch',{name:'Автонарезка для rezak_ui_test',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('[aria-label="Автонарезка для rezak_ui_test"]').getAttribute('aria-checked')==='false');
  await page.screenshot({path:path.join(dir,'twitch.png'),fullPage:true});
  await page.getByRole('button',{name:'Настройки',exact:true}).click();
  await page.getByRole('heading',{name:'Настройки',exact:true}).waitFor();
  await page.screenshot({path:path.join(dir,'settings.png'),fullPage:true});
  await page.getByLabel('Client ID',{exact:true}).fill('test-client-id');
  await page.waitForTimeout(1800);
  if(await page.getByLabel('Client ID',{exact:true}).inputValue()!=='test-client-id')throw new Error('Settings input reset during refresh');
  await page.getByRole('link',{name:/Очередь обработки/}).click();
  await page.getByRole('heading',{name:'Очередь обработки',exact:true}).waitFor();
  const before=await page.evaluate(async()=>await(await fetch('/api/status')).json());
  if(!before.jobs.some(j=>j.title==='Проверка интерфейса.mp4')) {
    if(!before.queue_paused)await page.getByRole('button',{name:'Пауза очереди',exact:true}).click();
    await page.locator('#file-input').setInputFiles({name:'Проверка интерфейса.mp4',mimeType:'video/mp4',buffer:fs.readFileSync('data/sources/smoke-story.mp4')});
    await page.getByRole('button').filter({hasText:'Проверка интерфейса.mp4'}).first().waitFor({timeout:30000});
  }
  await page.screenshot({path:path.join(dir,'queue.png'),fullPage:true});
  await page.getByRole('link',{name:/Готовые нарезки/}).click();
  await page.getByRole('heading',{name:'Готовые нарезки',exact:true}).waitFor();
  await page.evaluate(()=>document.querySelectorAll('.clip-preview img').forEach(i=>i.loading='eager'));
  await page.waitForFunction(()=>[...document.querySelectorAll('.clip-preview img')].every(i=>i.complete&&i.naturalWidth>0));
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:path.join(dir,'clips.png'),fullPage:true});
  await page.locator('[data-action="play"]').first().click();
  await page.locator('#player-dialog').waitFor({state:'visible'});
  await page.waitForFunction(()=>document.getElementById('player').readyState>=2);
  await page.keyboard.press('Escape');
  await page.getByRole('link',{name:/Обзор/}).click();
  await page.setViewportSize({width:430,height:932});
  await page.screenshot({path:path.join(dir,'mobile.png'),fullPage:true});
  const mobile=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));
  const data=await page.evaluate(async()=>await(await fetch('/api/status')).json());
  const test=data.streamers.find(s=>s.login==='rezak_ui_test');
  if(test)await page.evaluate(async id=>await fetch('/api/streamers/'+id,{method:'DELETE',headers:{'X-Rezak-Client':'1'}}),test.id);
  console.log(JSON.stringify({layout,mobile,errors,queuedJob:data.jobs.find(j=>j.title==='Проверка интерфейса.mp4')?.id, screenshots:dir},null,2));

  if(errors.length||layout.scroll>layout.width||mobile.scroll>mobile.width)process.exitCode=1;
  } finally {await browser.close();}
}
main().catch(err=>{console.error(err);process.exit(1)});
