const {describe,it}=require('node:test');
const assert=require('node:assert/strict');
const hf=require('../runtime/hf.cjs');

describe('hugging face adapters',()=>{
  it('classifies chat/tools/vision/coding/reasoning/embeddings/audio',()=>{
    assert.equal(hf.inferCapabilities({id:'Qwen/Qwen3-4B',tags:['conversational'],pipeline_tag:'text-generation'}).chat,true);
    assert.ok(hf.inferCapabilities({id:'x/tool-calling-7b',tags:['tool-use'],pipeline_tag:'text-generation'}).tools);
    assert.ok(hf.inferCapabilities({id:'google/gemma-3-4b-it',tags:['image-text-to-text'],pipeline_tag:'image-text-to-text'}).vision);
    assert.ok(hf.inferCapabilities({id:'Qwen/Qwen2.5-Coder-7B-Instruct',tags:['codegen'],pipeline_tag:'text-generation'}).coding);
    assert.ok(hf.inferCapabilities({id:'openai/gpt-oss-20b',tags:['reasoning'],pipeline_tag:'text-generation'}).reasoning);
    assert.ok(hf.inferCapabilities({id:'XHToken/Spark-X2.5-4B-GGUF',tags:['gguf'],pipeline_tag:'text-generation'}).reasoning);
    const emb=hf.inferCapabilities({id:'sentence-transformers/all-MiniLM',tags:['sentence-transformers'],pipeline_tag:'sentence-similarity'});
    assert.ok(emb.embeddings&&!emb.chat);
    const au=hf.inferCapabilities({id:'openai/whisper-large',tags:['audio'],pipeline_tag:'automatic-speech-recognition'});
    assert.ok(au.audio&&!au.chat);
  });
  it('extracts quant labels from filenames',()=>{
    assert.equal(hf.quantFromName('model-Q4_K_M.gguf'),'Q4_K_M');
    assert.equal(hf.quantFromName('model-q8_0.gguf'),'Q8_0');
    assert.equal(hf.quantFromName('model-IQ4_XS.gguf'),'IQ4_XS');
  });
  it('builds exact Hugging Face resolve URLs (single-file download, never whole repo)',()=>{
    assert.equal(hf.resolveUrl('X/Y','dir/f.gguf'),'https://huggingface.co/X/Y/resolve/main/dir/f.gguf?download=true');
  });
  it('estimates hardware fit from real file size (not params alone)',()=>{
    const item={gguf:{total:4200000000},safetensors:{total:0}};
    assert.equal(hf.estimateCompatibility(item,{ramGb:15.6,nvidia:[]}).level,'great');
    assert.equal(hf.estimateCompatibility(item,{ramGb:2,nvidia:[]}).level,'no');
    assert.equal(hf.estimateCompatibility({},{ramGb:16,nvidia:[]}).level,'unknown');
  });
});
