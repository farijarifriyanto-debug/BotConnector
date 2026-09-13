const {TOOL_DEFINITIONS}=require('../../runtime/tools.cjs');

class BotConnectorError extends Error{
  constructor(message,{status=0,code='BOTCONNECTOR_ERROR',body=null}={}){super(message);this.name='BotConnectorError';this.status=status;this.code=code;this.body=body;}
}

function joinUrl(base,path){return `${String(base||'http://127.0.0.1:11435/v1').replace(/\/+$/,'')}/${String(path).replace(/^\/+/,'')}`;}
function originOf(base){const u=new URL(base);return `${u.protocol}//${u.host}`;}

class BotConnectorClient{
  constructor(options={}){this.baseUrl=String(options.baseUrl||'http://127.0.0.1:11435/v1').replace(/\/+$/,'');this.apiKey=options.apiKey?String(options.apiKey):'';this.timeoutMs=Math.max(250,Number(options.timeoutMs||30000));}
  async #request(path,{method='GET',body,signal}={}){
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),this.timeoutMs);const onAbort=()=>controller.abort();if(signal?.aborted)controller.abort();else signal?.addEventListener('abort',onAbort,{once:true});
    try{const headers={Accept:'application/json'};if(body!==undefined){headers['Content-Type']='application/json';}if(this.apiKey)headers.Authorization=`Bearer ${this.apiKey}`;const res=await fetch(joinUrl(this.baseUrl,path),{method,headers,body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});const text=await res.text();let data=null;try{data=text?JSON.parse(text):null;}catch{data=text||null;}if(!res.ok)throw new BotConnectorError(data?.error?.message||`BotConnector API returned ${res.status}`,{status:res.status,code:data?.error?.code||'HTTP_ERROR',body:data});return data;}
    catch(error){if(error instanceof BotConnectorError)throw error;if(error.name==='AbortError')throw new BotConnectorError('BotConnector request timed out or was aborted',{code:'ABORTED'});throw new BotConnectorError(error.message||String(error),{code:'NETWORK_ERROR'});}
    finally{clearTimeout(timer);signal?.removeEventListener('abort',onAbort);}
  }
  models={list:()=>this.#request('/models'),get:(id)=>this.#request(`/models/${encodeURIComponent(id)}`)};
  chat={create:(request,options={})=>this.#request('/chat/completions',{method:'POST',body:{...request,stream:false},...options}),stream:(request,options={})=>this.#stream('/chat/completions',{...request,stream:true},options)};
  embeddings={create:(request,options={})=>this.#request('/embeddings',{method:'POST',body:request,...options})};
  runtime={status:async()=>{const [health,models]=await Promise.all([this.#requestFromOrigin('/health'),this.models.list().catch(()=>null)]);return {healthy:health?.status==='ok'||health?.status==='ready'||health===true,status:health?.status||'ok',models};}};
  tools={list:async()=>TOOL_DEFINITIONS.map(t=>({name:t.function?.name||t.name,description:t.function?.description||t.description||'',source:'BotConnector Core',permission:'allowlisted'}))};
  async #requestFromOrigin(path){const originClient=new BotConnector({baseUrl:originOf(this.baseUrl),apiKey:this.apiKey,timeoutMs:this.timeoutMs});return originClient.#request(path);}
  async *#stream(path,body,{signal}={}){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),this.timeoutMs),onAbort=()=>controller.abort();if(signal?.aborted)controller.abort();else signal?.addEventListener('abort',onAbort,{once:true});try{const headers={'Content-Type':'application/json',Accept:'text/event-stream'};if(this.apiKey)headers.Authorization=`Bearer ${this.apiKey}`;const res=await fetch(joinUrl(this.baseUrl,path),{method:'POST',headers,body:JSON.stringify(body),signal:controller.signal});if(!res.ok){const text=await res.text();let data;try{data=JSON.parse(text)}catch{data=null}throw new BotConnectorError(data?.error?.message||`BotConnector API returned ${res.status}`,{status:res.status,code:data?.error?.code||'HTTP_ERROR',body:data||text});}const reader=res.body.getReader(),decoder=new TextDecoder();let buffer='';while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const lines=buffer.split(/\r?\n/);buffer=lines.pop()||'';for(const line of lines){if(!line.startsWith('data:'))continue;const raw=line.slice(5).trim();if(!raw)continue;if(raw==='[DONE]')return;try{yield JSON.parse(raw)}catch{throw new BotConnectorError('Malformed SSE event from BotConnector',{code:'MALFORMED_STREAM'})}}}}catch(error){if(error instanceof BotConnectorError)throw error;if(error.name==='AbortError')throw new BotConnectorError('BotConnector stream timed out or was aborted',{code:'ABORTED'});throw new BotConnectorError(error.message||String(error),{code:'NETWORK_ERROR'});}finally{clearTimeout(timer);signal?.removeEventListener('abort',onAbort);}}
}
module.exports={BotConnectorClient,BotConnectorError};
