import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {existsSync,mkdtempSync,mkdirSync,readFileSync,writeFileSync,symlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {validateDataset,validateDirectorTarget,prepareDataset} from '../scripts/prepare-multimedia-director-data.mjs';

const PNG=[
 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGO8wyXHwMDAxMDAwMDAAAANGAEIahSdtwAAAABJRU5ErkJggg==',
 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPkMrrDwMDAxMDAwMDAAAAMeAEc4HHGxwAAAABJRU5ErkJggg==',
 'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGPkOWXDwMDAxMDAwMDAAAAM0gEWH4WAtQAAAABJRU5ErkJggg==',
];
const registry={records:[
 {id:'abo',status:'candidate_allowed_with_attribution',license:'CC-BY-4.0'},
 {id:'shot2story',status:'block_commercial',license:'CC-BY-NC-SA-4.0'},
 {id:'met',status:'candidate_filter_per_image',license:'CC0 only public domain open access images'},
 {id:'finevideo',status:'conditional_approval_required',license:'CC-BY per source + gated terms'},
 {id:'fxi',status:'candidate_text_only',license:'CC-BY-4.0 for text'}
]};
const target=task=>({
 schema:'botconnector.multimedia-director.v1',task,
 visual:{observed_facts:['Botol biru'],unknowns:['Teks kecil tidak terbaca']},
 preservation_rules:['Jangan ubah label asli'],
 ...(task==='product_photo'||task==='ad_creative'?{concepts:[
  {title:'Premium',scene:'Studio biru',mood:'Soft light',tagline:'Elegan'},
  {title:'Lifestyle',scene:'Meja kayu',mood:'Daylight',tagline:'Sehari-hari'},
  {title:'Bold',scene:'Latar geometris',mood:'High contrast',tagline:'Berani'},
 ]}:{shots:[
  {camera:'tracking',action:'Berjalan',subject_lock:'Jaket merah',duration_seconds:5},
  {camera:'closeup',action:'Menoleh',subject_lock:'Jaket merah',duration_seconds:5},
 ]})
});
function fixture(){
 const work=mkdtempSync(join(tmpdir(),'bico-dataset-')),root=join(work,'assets');mkdirSync(root);
 const rows=PNG.map((s,i)=>{
  const buf=Buffer.from(s,'base64');writeFileSync(join(root,'product-'+i+'.png'),buf);
  return {id:'record-'+i,source_id:'abo',license:'CC-BY-4.0',
   attribution:'Test-only attribution, not a real ABO image',
   asset_path:'product-'+i+'.png',asset_sha256:createHash('sha256').update(buf).digest('hex'),
   task:'product_photo',split:['train','val','test'][i],group_id:'sku-'+i,
   brief:'Susun konsep foto produk berdasarkan gambar, tanpa mengarang tulisan atau merek.',
   rights:{commercial_training_allowed:true,third_party_compute_allowed:true,
    contains_customer_data:false,contains_pii:false,contains_identifiable_people:false,
    asset_rights_reviewed:true,evidence_url:'https://registry.opendata.aws/amazon-berkeley-objects/'},
   review:{status:'approved',reviewer_id:'synthetic-test',reviewed_at:'2026-10-31'},
   target:target('product_photo')};
 });
 return {work,root,rows};
}
function expectGate(rows,root,code,reg=registry){
 assert.throws(()=>validateDataset(rows,reg,{assetsRoot:root}),e=>{assert.equal(e.code,code);return true;});
}
test('stages licensed records into three isolated splits',()=>{
 const {rows,root}=fixture(),v=validateDataset(rows,registry,{assetsRoot:root});
 assert.deepEqual(v.counts,{train:1,val:1,test:1});
 assert.equal(v.unique_images,3);
 assert.equal(v.records[0].image_path,'product-0.png');
 assert.equal('image_base64' in v.records[0],false);
});
test('rejects noncommercial sources even when flags say otherwise',()=>{
 const {rows,root}=fixture();rows[0].source_id='shot2story';
 expectGate(rows,root,'blocked_source');
});
test('rejects text-only camera dataset for image training',()=>{
 const {rows,root}=fixture();rows[0].source_id='fxi';
 expectGate(rows,root,'blocked_source');
});
test('requires explicit community compute and non-sensitive media flags',()=>{
 const {rows,root}=fixture();rows[0].rights.third_party_compute_allowed=false;
 expectGate(rows,root,'rights_not_cleared');
 rows[0].rights.third_party_compute_allowed=true;rows[0].rights.contains_identifiable_people=true;
 expectGate(rows,root,'rights_not_cleared');
});
test('requires evidence URL and human review',()=>{
 const {rows,root}=fixture();rows[0].rights.evidence_url='';
 expectGate(rows,root,'license_evidence_missing');
 rows[0].rights.evidence_url='https://registry.opendata.aws/amazon-berkeley-objects/';
 rows[0].review.status='pending';expectGate(rows,root,'human_review_missing');
});
test('conditional FineVideo requires terms acceptance',()=>{
 const {rows,root}=fixture();rows[0].source_id='finevideo';
 expectGate(rows,root,'dataset_terms_not_accepted');
 rows[0].rights.dataset_terms_accepted=true;
 assert.equal(validateDataset(rows,registry,{assetsRoot:root}).counts.train,1);
});
test('CC0 source only with correct per-asset license',()=>{
 const {rows,root}=fixture();rows[0].source_id='met';rows[0].license='CC0-1.0';rows[0].attribution='';
 assert.equal(validateDataset(rows,registry,{assetsRoot:root}).counts.train,1);
 rows[0].license='CC-BY-4.0';expectGate(rows,root,'license_mismatch');
});
test('fails on an actual asset checksum mismatch',()=>{
 const {rows,root}=fixture();rows[0].asset_sha256='a'.repeat(64);
 expectGate(rows,root,'asset_checksum_mismatch');
});
test('same SKU in train/test is blocked even for different photos',()=>{
 const {rows,root}=fixture();rows[2].group_id=rows[0].group_id;
 expectGate(rows,root,'group_split_leakage');
});
test('same image in train/test is blocked even for different SKU IDs',()=>{
 const {rows,root}=fixture();rows[2].asset_path=rows[0].asset_path;
 rows[2].asset_sha256=rows[0].asset_sha256;
 expectGate(rows,root,'image_split_leakage');
});
test('global grouping blocks the same product across different sources',()=>{
 const {rows,root}=fixture();
 rows[2].source_id='met';rows[2].license='CC0-1.0';rows[2].attribution='';
 rows[2].group_id=rows[0].group_id;
 expectGate(rows,root,'group_split_leakage');
});
test('duplicate identifiers are blocked',()=>{
 const {rows,root}=fixture();rows[1].id=rows[0].id;
 expectGate(rows,root,'duplicate_or_invalid_id');
});
test('path traversal and symlink escapes are blocked',()=>{
 const {rows,root,work}=fixture();rows[0].asset_path='../sensitive.png';
 expectGate(rows,root,'invalid_asset_path');
 const outside=join(work,'outside.png');writeFileSync(outside,Buffer.from(PNG[0],'base64'));
 symlinkSync(outside,join(root,'escape.png'));rows[0].asset_path='escape.png';
 expectGate(rows,root,'asset_path_escape');
});
test('contract rejects repeated concepts and invalid shot length',()=>{
 const a=target('product_photo');assert.deepEqual(validateDirectorTarget(a,'product_photo'),[]);
 a.concepts[1].scene=a.concepts[0].scene;
 assert.ok(validateDirectorTarget(a,'product_photo').includes('invalid_concepts'));
 const b=target('video_direction');assert.deepEqual(validateDirectorTarget(b,'video_direction'),[]);
 b.shots[0].duration_seconds=20;
 assert.ok(validateDirectorTarget(b,'video_direction').includes('invalid_shots'));
});
test('default dataset gate blocks too few heldout cases without creating output',()=>{
 const {rows,root,work}=fixture(),m=join(work,'manifest.jsonl'),r=join(work,'registry.json'),o=join(work,'out');
 writeFileSync(m,rows.map(x=>JSON.stringify(x)).join('\n'));
 writeFileSync(r,JSON.stringify(registry));
 assert.throws(()=>prepareDataset({manifestPath:m,registryPath:r,assetsRoot:root,outDir:o}),e=>e.code==='insufficient_dataset');
 assert.equal(existsSync(o),false);
 const run=prepareDataset({manifestPath:m,registryPath:r,assetsRoot:root,outDir:o,smoke:true});
 assert.equal(run.mode,'smoke_only');
 assert.equal(readFileSync(join(o,'test.jsonl'),'utf8').trim().split('\n').length,1);
 assert.throws(()=>prepareDataset({manifestPath:m,registryPath:r,assetsRoot:root,outDir:o,smoke:true}),e=>e.code==='output_exists');
});
test('smoke CLI runs locally without GPU, network, or heavy dependencies',()=>{
 const {rows,root,work}=fixture(),m=join(work,'manifest.jsonl'),r=join(work,'registry.json'),o=join(work,'out');
 writeFileSync(m,rows.map(x=>JSON.stringify(x)).join('\n'));writeFileSync(r,JSON.stringify(registry));
 const script=new URL('../scripts/prepare-multimedia-director-data.mjs',import.meta.url);
 const run=spawnSync(process.execPath,[script.pathname,'--manifest',m,'--registry',r,'--assets-root',root,'--out',o,'--smoke'],{encoding:'utf8'});
 assert.equal(run.status,0,run.stderr);assert.equal(JSON.parse(run.stdout).mode,'smoke_only');
});
