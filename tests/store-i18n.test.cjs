const {describe,it}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const vm=require('node:vm');
const {Store}=require('../runtime/store.cjs');

describe('settings store',()=>{
  it('roundtrips settings and survives reload',async()=>{
    const dir=await fsp.mkdtemp(path.join(os.tmpdir(),'bc-store-'));
    const s=new Store(dir);
    assert.equal(s.get('runtimeBackend'),'auto');
    assert.ok(s.get('modelsDir').length>0);
    await s.set('runtimeBackend','vulkan');
    await s.set('language','id');
    const s2=new Store(dir);s2.load();
    assert.equal(s2.get('runtimeBackend'),'vulkan');
    assert.equal(s2.get('language'),'id');
    const pub=s2.public();
    assert.ok(!('hfTokenEncrypted' in pub),'encrypted token never exposed via public()');
  });
});

describe('i18n parity (en/id)',()=>{
  it('every user-visible key exists in both languages, technical identifiers untranslated',()=>{
    const src=fs.readFileSync(path.join(__dirname,'..','desktop','i18n.js'),'utf8');
    const sandbox={window:{},navigator:{language:'en'}};
    vm.runInNewContext(src,sandbox);
    const d=sandbox.window.BotI18n.d;
    assert.ok(d.en&&d.id);
    const keys=(o,pfx='')=>Object.entries(o).flatMap(([k,v])=>typeof v==='object'&&!Array.isArray(v)?keys(v,pfx+k+'.'):[pfx+k]);
    assert.deepEqual(keys(d.id).sort(),keys(d.en).sort());
    assert.equal(sandbox.window.BotI18n.resolve('id'),'id');
    assert.equal(sandbox.window.BotI18n.resolve('system',['id-ID']),'id');
    assert.equal(sandbox.window.BotI18n.t('id','nav.installed'),'Terpasang');
    assert.equal(sandbox.window.BotI18n.t('xx','nav.home'),'Home','unknown locale falls back to English');
    assert.equal(sandbox.window.BotI18n.t('en','nav.nope'),'nav.nope','missing key returns path');
    for(const tech of ['GGUF','Q4_K_M','CUDA','Vulkan','API']){
      const ui=fs.readFileSync(path.join(__dirname,'..','desktop','desktop.js'),'utf8')
        +fs.readFileSync(path.join(__dirname,'..','desktop','index.html'),'utf8');
      assert.match(ui,new RegExp(tech),'technical identifier stays untranslated in UI code');
    }
  });
});
