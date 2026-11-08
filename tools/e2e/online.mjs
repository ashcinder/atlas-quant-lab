import {chromium} from '../../frontend/node_modules/playwright/index.mjs'
import {readFile,writeFile} from 'node:fs/promises'
const runPath=process.argv[2];const run=JSON.parse(await readFile(runPath+'/run.json'));if(!run.synthetic_only||run.port===18095)throw Error('Isolated target required')
const browser=await chromium.launch();const context=await browser.newContext({baseURL:run.origin});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));const rows=[]
try{
 await page.goto('/');await page.getByLabel('登录邮箱').fill('author@e2e.example.test');await page.getByLabel('密码',{exact:true}).fill('Only-E2E-Fixture-2026!');await page.getByRole('button',{name:'登录 Atlas',exact:true}).click();await page.getByRole('button',{name:'运行回测',exact:true}).waitFor()
 for(const [symbol,asset_class,interval,data_source]of [['BTC-USD','crypto','1d','auto'],['ETH-USD','crypto','1h','auto'],['SPY','etf','1d','yahoo']]){
  const query=new URLSearchParams({symbol,asset_class,interval,data_source,adjustment:'auto'});const r=await page.request.get('/api/v1/market/manifest?'+query);if(!r.ok())throw Error('Manifest '+r.status());const m=await r.json();if(/synthetic|demo/i.test(m.source)||m.is_stale)throw Error('Not a fresh real dataset');rows.push({symbol,source:m.source,count:m.count,id:m.dataset_id,is_stale:m.is_stale,source_note:m.source_note})
 }
 const result=page.waitForResponse(r=>r.url().endsWith('/api/v1/compute/runs')&&r.request().method()==='POST');await page.getByRole('button',{name:'运行回测',exact:true}).click();const response=await result;if(!response.ok())throw Error('Real market backtest '+response.status());const saved=await response.json();if(saved.data_source!=='binance'||saved.compute?.execution_location!=='browser')throw Error('Wrong actual data provenance');await page.getByRole('region',{name:'回测结果'}).getByText('总收益',{exact:true}).waitFor()
 if(!saved.compute.dataset_ids.includes(rows[0].id)||saved.equity.length!==rows[0].count)throw Error('Saved equity series does not match the published dataset')
 if(errors.length)throw Error(errors.join(';'));await writeFile(runPath+'/online-result.json',JSON.stringify({passed:true,datasets:rows,browser_backtest:{source:saved.data_source,equity_points:saved.equity.length,dataset_id:rows[0].id,proof_status:saved.compute.proof_status},errors},null,2));console.log('Real public Binance/Sina datasets and compiled browser backtest passed')
}finally{await context.close();await browser.close()}
