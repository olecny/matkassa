// Run: node test/unit.test.mjs   (no dependencies)
import {detectImport,summarize,parseWhen,toNumber} from '../js/spending.js';
import {makeClassifier,DEFAULT_CATEGORIES} from '../js/categories.js';
const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m); if(!c) process.exitCode=1;};
// Trumf bare array, as in trumf_receipt_tools
const t=detectImport([{dato:'03.10.2026 12:05',kvitteringsnummer:'A1',kjede:'KIWI',butikknavn:'KIWI Moholt',varelinjer:[{varenavn:'TINE LETTMELK',vareAntallVekt:'1,000',vareBelop:'24,90'},{varenavn:'PANT',vareAntallVekt:'1',vareBelop:'2,00'}]}]);
ok(t.kind==='trumf'&&t.data[0].date==='2026-10-03'&&t.data[0].total===26.9,'trumf bare array');
// Trumf date only, numbers as numbers, wrapper object
const t2=detectImport({data:{kvitteringer:[{dato:'03.10.2026',kvitteringsnummer:5,kjede:'MENY',varelinjer:[{varenavn:'X',vareBelop:10}]}]}});
ok(t2.kind==='trumf'&&t2.data[0].total===10&&t2.data[0].time===null,'trumf wrapped + date only');
const s=detectImport({schema:'matkassa.spending/1',receipts:[{id:'r1',source:'rema',store:'REMA',date:'2026-10-20',total:100,lines:[{name:'COLA',amount:91.9,group:'BRUS (STOR)'},{name:'????',amount:8.1}]}]});
ok(s.kind==='spending'&&s.data[0].lines.length===2,'spending.json');
const cls=makeClassifier(DEFAULT_CATEGORIES,[{type:'text',pattern:'????',categoryId:'annet'}]);
const sum=summarize(s.data,cls,DEFAULT_CATEGORIES);const m=sum.months.get('2026-10');
ok(Math.abs(m.total-100)<1e-9 && Math.abs([...m.byCat.values()].reduce((a,b)=>a+b,0)-100)<1e-9,'month total == sum of categories == receipts');
ok(m.byCat.get('drikke')===91.9,'group/keyword → drikke');
ok(toNumber('1.234,50')===1234.5 && toNumber('24,90 kr')===24.9,'toNumber');
try{detectImport({foo:1});ok(false,'reject junk')}catch(e){ok(/Fant ingen/.test(e.message),'reject junk')}
