#!/usr/bin/env node
// Offline, fail-closed data gate. No downloads, GPU, customer media, or training.
import {createHash} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,realpathSync,renameSync,rmSync,statSync,writeFileSync} from 'node:fs';
import {dirname,isAbsolute,join,resolve,sep} from 'node:path';
import {pathToFileURL} from 'node:url';

export const DATASET_SCHEMA='botconnector.multimedia-dataset.v1';
export const DIRECTOR_SCHEMA='botconnector.multimedia-director.v1';
export const TASKS=new Set(['product_photo','ad_creative','storyboard','video_direction']);
export const SPLITS=new Set(['train','val','test']);
const ELIGIBLE=new Set(['candidate_allowed_with_attribution','candidate_with_human_quality_review','candidate_filter_per_image','candidate_filter_per_asset','conditional_approval_required']);
const str=x=>typeof x==='string'?x.trim():'';
const obj=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const words=x=>Array.isArray(x)&&x.every(v=>str(v).length>0);
const deny=(code,detail)=>{const e=new Error(code+': '+detail);e.code=code;throw e;};

export function readJsonl(path) {
 return readFileSync(path,'utf8').split(/\r?\n/).map((line,i)=>({line:line.trim(),n:i+1}))
  .filter(x=>x.line&&!x.line.startsWith('#')).map(x=>{
   try{return JSON.parse(x.line);}
   catch{return deny('bad_jsonl',path+':'+x.n);}
  });
}
export function validateDirectorTarget(target,task) {
 if(!obj(target)||target.schema!==DIRECTOR_SCHEMA||target.task!==task)return ['invalid_target_schema_task'];
 const errors=[];
 if(!obj(target.visual)||!words(target.visual.observed_facts)||!target.visual.observed_facts.length||!words(target.visual.unknowns))errors.push('invalid_visual_facts');
 if(!words(target.preservation_rules)||!target.preservation_rules.length)errors.push('invalid_preservation_rules');
 if(task==='product_photo'||task==='ad_creative'){
  const c=target.concepts;
  if(!Array.isArray(c)||c.length!==3||c.some(v=>!obj(v)||!['title','scene','mood','tagline'].every(k=>str(v[k])))||
    new Set((c||[]).map(v=>str(v?.scene).toLowerCase().replace(/\s+/g,' '))).size!==3)errors.push('invalid_concepts');
 }else{
  const s=target.shots;
  if(!Array.isArray(s)||s.length<2||s.length>24||s.some(v=>!obj(v)||!['camera','action','subject_lock'].every(k=>str(v[k]))||
   !Number.isFinite(v.duration_seconds)||v.duration_seconds<=0||v.duration_seconds>10))errors.push('invalid_shots');
 }
 return errors;
}
function inspectAsset(root,path,digest) {
 const name=str(path);
 if(!name||isAbsolute(name)||name.startsWith('/')||name.includes('\\')||name.includes('\0')||name.split('/').includes('..')||!/\.(png|jpe?g|webp)$/i.test(name))deny('invalid_asset_path',name);
 const pathAbs=resolve(root,name);
 if(pathAbs===root||!pathAbs.startsWith(root+sep))deny('invalid_asset_path',name);
 if(!existsSync(pathAbs))deny('missing_asset',name);
 const real=realpathSync(pathAbs);
 if(!real.startsWith(root+sep)||!statSync(real).isFile())deny('asset_path_escape',name);
 const bytes=readFileSync(real);
 if(bytes.length<32||bytes.length>25*1024*1024)deny('image_size',name);
 const png=bytes.subarray(0,8).equals(Buffer.from('89504e470d0a1a0a','hex'));
 const jpg=bytes[0]===255&&bytes[1]===216&&bytes[2]===255;
 const webp=bytes.subarray(0,4).toString('ascii')==='RIFF'&&bytes.subarray(8,12).toString('ascii')==='WEBP';
 if(!png&&!jpg&&!webp)deny('bad_image_signature',name);
 const actual=createHash('sha256').update(bytes).digest('hex');
 if(actual!==digest.toLowerCase())deny('asset_checksum_mismatch',name);
 return actual;
}
function validateRights(row,source) {
 const r=row.rights;
 if(!obj(r)||r.commercial_training_allowed!==true||r.third_party_compute_allowed!==true||
    r.contains_customer_data!==false||r.contains_pii!==false||r.contains_identifiable_people!==false||r.asset_rights_reviewed!==true)deny('rights_not_cleared',row.id);
 if(!/^https:\/\//.test(str(r.evidence_url)))deny('license_evidence_missing',row.id);
 if(!obj(row.review)||row.review.status!=='approved'||!str(row.review.reviewer_id)||!/^\d{4}-\d{2}-\d{2}$/.test(str(row.review.reviewed_at)))deny('human_review_missing',row.id);
 if(source.status==='conditional_approval_required'&&r.dataset_terms_accepted!==true)deny('dataset_terms_not_accepted',row.id);
 const declared=str(source.license).toUpperCase(),license=str(row.license);
 const eligible=license==='CC-BY-4.0'?/CC[- ]?BY/.test(declared):license==='CC0-1.0'&&/CC0|PUBLIC.DOMAIN/.test(declared);
 if(!eligible)deny('license_mismatch',row.id);
 if(license==='CC-BY-4.0'&&!str(row.attribution))deny('attribution_missing',row.id);
}
export function validateDataset(records,registry,{assetsRoot}={}) {
 if(!Array.isArray(records)||!records.length)deny('empty_dataset','no records');
 if(!obj(registry)||!Array.isArray(registry.records))deny('bad_registry','missing records');
 const root=realpathSync(assetsRoot||'.');
 const sources=new Map(registry.records.map(x=>[x.id,x]));
 const ids=new Set(),shaSplits=new Map(),groupSplits=new Map(),data=[];
 for(const row of records){
  if(!obj(row)||!/^[a-z0-9_.:-]{4,128}$/i.test(str(row.id))||ids.has(row.id))deny('duplicate_or_invalid_id',row?.id);
  ids.add(row.id);
  if(!TASKS.has(row.task)||!SPLITS.has(row.split))deny('invalid_task_or_split',row.id);
  if(!/^[a-z0-9_.:-]{4,128}$/i.test(str(row.group_id)))deny('invalid_group',row.id);
  const source=sources.get(row.source_id);
  if(!source)deny('unknown_source',row.id);
  if(!ELIGIBLE.has(source.status))deny('blocked_source',row.id+':'+source.status);
  validateRights(row,source);
  if(!str(row.brief)||row.brief.length>3000)deny('invalid_brief',row.id);
  if(!/^[a-f0-9]{64}$/i.test(str(row.asset_sha256)))deny('invalid_sha256',row.id);
  const digest=inspectAsset(root,row.asset_path,row.asset_sha256);
  // group_id must be a globally stable product/character/project identity across all sources.
  const group=row.group_id;
  if(groupSplits.has(group)&&groupSplits.get(group)!==row.split)deny('group_split_leakage',row.id);
  if(shaSplits.has(digest)&&shaSplits.get(digest)!==row.split)deny('image_split_leakage',row.id);
  groupSplits.set(group,row.split);shaSplits.set(digest,row.split);
  const errors=validateDirectorTarget(row.target,row.task);
  if(errors.length)deny('bad_annotation',row.id+':'+errors.join(','));
  // Staging only: NOT a ready-to-feed TRL/SFTTrainer dataset; multimodal processor and label masks required.
  data.push({schema:DATASET_SCHEMA,id:row.id,task:row.task,split:row.split,image_path:row.asset_path,
    image_sha256:digest,group_id:group,source_id:row.source_id,license:row.license,
    attribution:row.attribution||null,brief:row.brief,target:row.target});
 }
 const counts=Object.fromEntries([...SPLITS].map(split=>[split,data.filter(v=>v.split===split).length]));
 return {records:data,counts,unique_groups:groupSplits.size,unique_images:shaSplits.size,
  gate:'human_rights_review_assertions_required_but_not_independently_verified',
  note:'Only header and SHA256 verified; full image decode, source ownership, PII, visual truth and label accuracy require independent human checks.'};
}
export function prepareDataset({manifestPath,registryPath,assetsRoot,outDir,smoke=false}) {
 if(!manifestPath||!registryPath||!assetsRoot||!outDir)deny('missing_arguments','manifest, registry, assets root, out required');
 const checked=validateDataset(readJsonl(manifestPath),JSON.parse(readFileSync(registryPath,'utf8')),{assetsRoot});
 const count=checked.counts;
 if(!smoke&&(count.train<50||count.val<10||count.test<200))deny('insufficient_dataset','need 50 train, 10 val, 200 heldout test');
 if(existsSync(outDir))deny('output_exists',outDir);
 const temp=outDir+'.tmp-'+process.pid;
 if(existsSync(temp))deny('output_temp_exists',temp);
 mkdirSync(dirname(resolve(outDir)),{recursive:true});mkdirSync(temp,{mode:0o700});
 try{
  for(const split of SPLITS){
   const lines=checked.records.filter(r=>r.split===split).map(r=>JSON.stringify(r));
   writeFileSync(join(temp,split+'.jsonl'),lines.join('\n')+(lines.length?'\n':''),{mode:0o600});
  }
  writeFileSync(join(temp,'summary.json'),JSON.stringify({schema:DATASET_SCHEMA,
   counts:checked.counts,unique_groups:checked.unique_groups,unique_images:checked.unique_images,
   mode:smoke?'smoke_only':'gated_dataset',gate:checked.gate,note:checked.note},null,2)+'\n',{mode:0o600});
  renameSync(temp,outDir);
 }catch(e){rmSync(temp,{recursive:true,force:true});throw e;}
 return {outDir,counts:count,mode:smoke?'smoke_only':'gated_dataset'};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
 try{
  const argv=process.argv.slice(2),o={smoke:false};
  const flags={'--manifest':'manifestPath','--registry':'registryPath','--assets-root':'assetsRoot','--out':'outDir'};
  for(let i=0;i<argv.length;i++){
   if(argv[i]==='--smoke'){o.smoke=true;continue;}
   if(!flags[argv[i]]||!argv[i+1])deny('bad_cli_argument',argv[i]);
   o[flags[argv[i]]]=argv[++i];
  }
  console.log(JSON.stringify(prepareDataset(o),null,2));
 }catch(e){console.error(e.code||'unexpected_error',e.message);process.exitCode=2;}
}
