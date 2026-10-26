const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});try{
 const p=await b.newPage({viewport:{width:1280,height:800},bypassCSP:true});const errors=[];p.on('pageerror',e=>errors.push(String(e)));
 await p.goto('http://127.0.0.1:8765');await p.waitForSelector('#log-content .log-line');
 // Simulate a previously cached stylesheet that requested smooth scrolling.
 await p.addStyleTag({content:'.log-content{scroll-behavior:smooth!important}'});
 const result=await p.evaluate(async()=>{
  const n=byId('log-content');state.autoScroll=true;renderLogs(true);const baseline=n.scrollTop;
  const descriptor=Object.getOwnPropertyDescriptor(Element.prototype,'scrollTop');let writes=0;
  Object.defineProperty(n,'scrollTop',{get(){return descriptor.get.call(this)},set(v){writes++;return descriptor.set.call(this,v)},configurable:true});
  const originalScroll=n.scrollTo.bind(n);let requests=0;n.scrollTo=(...args)=>{requests++;return originalScroll(...args)};
  const positions=[];for(let i=0;i<40;i++){state.data.system.free_bytes-=1;render();await new Promise(r=>requestAnimationFrame(r));positions.push(n.scrollTop);}
  const idleRequests=requests;const idleWrites=writes;
  const originalLogs=state.logs;state.logs=[...originalLogs,{id:999999,at:Date.now()/1000,level:'info',message:'UI-only regression: append at end'}];renderLogs();const immediateBottom=n.scrollHeight-n.clientHeight-n.scrollTop;
  const followRequests=requests-idleRequests;
  state.autoScroll=false;n.scrollTo({top:100,behavior:'instant'});await new Promise(r=>requestAnimationFrame(r));const before=n.scrollTop;
  state.logs=[...state.logs,{id:1000000,at:Date.now()/1000,level:'info',message:'UI-only regression: preserve history'}];renderLogs();await refresh(true);const after=n.scrollTop;
  state.logs=originalLogs;delete n.scrollTop;return{baseline,min:Math.min(...positions),max:Math.max(...positions),idleRequests,idleWrites,followRequests,immediateBottom,before,after,same:n===byId('log-content')};
 });
 assert.equal(result.min,result.baseline);assert.equal(result.max,result.baseline);assert.equal(result.idleRequests,0);assert.equal(result.idleWrites,0);assert.equal(result.followRequests,1);assert(result.immediateBottom<2);assert.equal(result.after,result.before);assert(result.same);assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,...result,errors}));
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
