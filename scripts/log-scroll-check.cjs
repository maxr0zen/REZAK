const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 const p=await browser.newPage();const errors=[];p.on('pageerror',e=>errors.push(String(e)));
 await p.goto('http://127.0.0.1:8765');await p.waitForSelector('#log-content .log-line');
 const result=await p.evaluate(async()=>{
   state.autoScroll=false;const node=byId('log-content');node.scrollTop=100;const before=node.scrollTop;
   render();const after=byId('log-content').scrollTop;const preserved=node===byId('log-content');
   const original=state.logs;state.logs=[...original,{id:999999,at:Date.now()/1000,level:'info',message:'UI-only regression event'}];
   renderLogs();const afterAppend=byId('log-content').scrollTop;
   state.autoScroll=true;renderLogs(true);const bottom=byId('log-content');const distance=bottom.scrollHeight-bottom.clientHeight-bottom.scrollTop;
   bottom.scrollTop=100;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
   const manualPaused=!state.autoScroll;await refresh(true);const afterRefresh=byId('log-content').scrollTop;
   state.logs=original;renderLogs();return{before,after,afterAppend,preserved,distance,manualPaused,afterRefresh};
 });
 assert(result.before>0);assert.equal(result.after,result.before);assert.equal(result.afterAppend,result.before);assert(result.preserved);assert(result.distance<2);assert(result.manualPaused);assert.equal(result.afterRefresh,result.before);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,...result,errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
