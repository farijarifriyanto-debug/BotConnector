import readline from 'node:readline';
const tools=[{name:'calculator',description:'Calculate 27 + 15 for acceptance',inputSchema:{type:'object',properties:{expression:{type:'string'}},required:['expression']}}];
function reply(id,result){process.stdout.write(JSON.stringify({jsonrpc:'2.0',id,result})+'\n');}
const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
rl.on('line',line=>{let m;try{m=JSON.parse(line);}catch{return;}if(m.method==='initialize')reply(m.id,{protocolVersion:'2025-11-25',capabilities:{tools:{}},serverInfo:{name:'fixture-calculator',version:'1'}});else if(m.method==='tools/list')reply(m.id,{tools});else if(m.method==='tools/call'){const expression=m.params?.arguments?.expression;if(m.params?.name!=='calculator'||expression!=='27 + 15')reply(m.id,{isError:true,content:[{type:'text',text:'unsupported expression'}]});else reply(m.id,{content:[{type:'text',text:'42'}],isError:false});}else if(m.id!=null)reply(m.id,{});});
