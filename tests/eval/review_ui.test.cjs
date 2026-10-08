// Exercise the actual inline review handlers with synthetic data and an in-memory
// DOM/storage adapter. No browser data or real human labels are read or written.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

const template = readFileSync(path.join(__dirname, '../../src/arbiter/eval/review_template.html'), 'utf8');
const script = [...template.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
const packet = {packet_id:'synthetic-ui-test', policy_version:'test', purpose:'UI test',
  cases:['a','b','c'].map(id=>({id,text:'Synthetic '+id,text_sha256:'hash-'+id}))};
const aiDraft = {draft_id:'synthetic-draft', labels:packet.cases.map(c=>({id:c.id,
  action:'allow',severity:0,categories:[],rationale:'Synthetic rationale',evidence_span:c.text,
  needs_attention:false,uncertainty:''}))};
const confirmed = id=>({id,text_sha256:'hash-'+id,gold_action:'human-review',gold_severity:1,
  gold_categories:['toxic'],rationale:'User-edited synthetic fixture',reviewed_at:'2026-09-22T12:00:00Z'});

function harness(labels={}, cached=null, storageFails=false){
  const ids = new Map();
  let downloads=0;
  const storage = cached || {value:JSON.stringify({reviewer:'test fixture',labels})};
  function element(tag='div'){
    return {tag,textContent:'',value:'',checked:false,hidden:false,disabled:false,style:{},children:[],scrolls:0,
      append(...children){this.children.push(...children)},
      querySelectorAll(selector){
        const inputs=this.children.flatMap(child=>child.children||[]).filter(child=>child.tag==='input');
        return selector==='input:checked'?inputs.filter(input=>input.checked):inputs;
      },
      querySelector(){return this.strong || (this.strong=element('strong'))},
      scrollIntoView(){this.scrolls++},click(){downloads++}};
  }
  const el = id=>{if(!ids.has(id))ids.set(id,element());return ids.get(id)};
  el('packet').textContent=JSON.stringify(packet);
  el('aiDraft').textContent=JSON.stringify(aiDraft);
  vm.runInNewContext(script, {
    document:{getElementById:el,createElement:element,createTextNode:text=>({textContent:text})},
    localStorage:{getItem:()=>storage.value,setItem:(_,value)=>{if(storageFails)throw Error('Storage full');storage.value=value}},
    Blob,URL,setTimeout
  });
  return {el,storage,downloads:()=>downloads,labels:()=>JSON.parse(storage.value).labels};
}

test('confirming the last row returns to an earlier skipped case and preserves edits',()=>{
  const existing=confirmed('b'), h=harness({b:existing});
  assert.match(h.el('caseId').textContent,/^1 \/ 3/);
  h.el('next').onclick();
  h.el('next').onclick();
  assert.match(h.el('caseId').textContent,/^3 \/ 3/);
  h.el('save').onclick();
  assert.match(h.el('caseId').textContent,/^1 \/ 3/);
  assert.match(h.el('message').textContent,/第 3 条已保存.*第 1 条未确认/);
  assert.match(h.el('completionStatus').textContent,/还有 1 条未确认/);
  assert.deepEqual(h.labels().b,existing);
  assert.equal(Object.keys(h.labels()).length,2);
});

test('final outstanding confirmation shows completion and export without attesting or downloading',()=>{
  const h=harness({a:confirmed('a'),b:confirmed('b')});
  assert.equal(h.el('save').textContent,'确认本条并完成');
  h.el('save').onclick();
  assert.equal(h.el('exportTitle').textContent,'全部确认完成 · 导出结果');
  assert.match(h.el('completionStatus').textContent,/3 条已全部确认/);
  assert.equal(h.el('remaining').hidden,true);
  assert.equal(h.el('exportSection').scrolls,1);
  assert.equal(h.el('attest').checked,false);
  h.el('export').onclick();
  assert.match(h.el('message').textContent,/勾选本人复核声明/);
  assert.equal(h.downloads(),0);
  const reloaded=harness({},h.storage);
  assert.match(reloaded.el('completionStatus').textContent,/3 条已全部确认/);
  assert.equal(reloaded.el('save').textContent,'保存本条修改');
  assert.equal(Object.keys(reloaded.labels()).length,3);
});

test('invalid final choice neither advances nor counts as confirmed',()=>{
  const h=harness({a:confirmed('a'),b:confirmed('b')});
  h.el('action').value='remove'; // Inconsistent with the prefilled severity zero.
  h.el('save').onclick();
  assert.match(h.el('caseId').textContent,/^3 \/ 3/);
  assert.match(h.el('message').textContent,/检查动作、严重程度/);
  assert.equal(Object.keys(h.labels()).length,2);
  assert.equal(h.el('exportSection').scrolls,0);
});

test('changing the AI label requires rewriting the AI rationale before confirming',()=>{
  const h=harness({a:confirmed('a'),b:confirmed('b')});
  h.el('action').value='human-review';h.el('severity').value='1';
  h.el('categories').querySelectorAll('input').find(input=>input.value==='identity_hate').checked=true;
  h.el('save').onclick();
  assert.match(h.el('message').textContent,/改写理由/);
  assert.equal(h.labels().c,undefined);
  h.el('rationale').value='Reviewer rewrote the synthetic rationale';
  h.el('save').onclick();
  assert.equal(h.labels().c.gold_action,'human-review');
  assert.equal(h.labels().c.rationale,'Reviewer rewrote the synthetic rationale');
});

test('remaining-case shortcut wraps without confirming anything',()=>{
  const h=harness({b:confirmed('b'),c:confirmed('c')});
  h.el('next').onclick();h.el('next').onclick();
  h.el('remaining').onclick();
  assert.match(h.el('caseId').textContent,/^1 \/ 3/);
  assert.equal(Object.keys(h.labels()).length,2);
});

test('storage failure does not claim durable save',()=>{
  const h=harness({a:confirmed('a'),b:confirmed('b')},null,true);
  h.el('save').onclick();
  assert.match(h.el('message').textContent,/浏览器未保存进度/);
  assert.equal(Object.keys(h.labels()).length,2);
});

test('explicit export exposes an identical text backup when download handling is unavailable',()=>{
  const h=harness({a:confirmed('a'),b:confirmed('b'),c:confirmed('c')});
  h.el('attest').checked=true; // Synthetic reviewer attestation, no actual user data.
  h.el('export').onclick();
  const exported=JSON.parse(h.el('exportJson').value);
  assert.equal(h.el('exportBackup').hidden,false);
  assert.equal(h.downloads(),1);
  assert.equal(exported.annotation_method,'ai_assisted');
  assert.equal(exported.attested_human_review,true);
  assert.deepEqual(exported.labels,Object.values(h.labels()));
});
