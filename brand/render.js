// node render.js  (needs playwright) -> avatar.png, banner.png
const {chromium}=require('playwright');const fs=require('fs'),path=require('path');
(async()=>{const b=await chromium.launch();for(const [n,w,h] of [['avatar',800,800],['banner',2560,1440]]){
const p=await b.newPage({viewport:{width:w,height:h}});
await p.setContent('<body style="margin:0;background:transparent">'+fs.readFileSync(path.join(__dirname,n+'.svg'),'utf8')+'</body>');
await p.evaluate(()=>document.fonts.ready);await p.waitForTimeout(500);
await p.screenshot({path:path.join(__dirname,n+'.png'),omitBackground:true});}
await b.close();})();
