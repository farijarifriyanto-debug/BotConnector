import readline from 'node:readline';
const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
rl.on('line',line=>{let m;try{m=JSON.parse(line)}catch{return}if(m.method==='initialize')process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:{protocolVersion:'2025-11-25',capabilities:{},serverInfo:{name:'timeout-fixture',version:'1'}}})+'\n');});
