// Default: no database writes. --pipeline submits only the generated synthetic PDF.
const { chromium } = require(process.argv[2] || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless:true,channel:'msedge'});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', () => errors.push('pageerror'));
    await page.goto('http://127.0.0.1:5173/', {waitUntil:'networkidle'});
    await page.getByRole('heading', {name:'上传个人银行流水', exact:true}).waitFor();
    if (!await page.getByRole('button', {name:'提交材料',exact:true}).isDisabled()) throw Error('Consent guard missing');
    await page.locator('input[type=file]').setInputFiles({name:'synthetic.txt',mimeType:'text/plain',buffer:Buffer.from('synthetic only')});
    await page.getByRole('alert').filter({hasText:'仅支持 PDF'}).waitFor();
    if (errors.length) throw Error('Browser runtime error');
    const evidence=path.resolve(__dirname,'../evidence');
    await page.screenshot({path:path.join(evidence,'20261031-upload-smoke.png'),fullPage:true});
    fs.writeFileSync(path.join(evidence,'20261031-web-smoke.json'),JSON.stringify({
      source:'real_browser',homepage:true,consent_guard:true,invalid_file_rejected:true,
      page_errors:0,database_writes:false,full_pipeline_tested:false
    },null,2)+'\n');
    console.log('PASS: real browser homepage, consent guard, invalid-file rejection; no upload submitted');
    if (process.argv.includes('--pipeline')) {
      const fixture=path.resolve(__dirname,'../inputs/demo_v2_uploads/synthetic-statement.pdf');
      await page.locator('input[type=file]').setInputFiles(fixture);
      await page.getByRole('checkbox').check();
      await page.getByRole('button',{name:'提交材料',exact:true}).click();
      await page.waitForURL(/\/tasks\/\d+$/, {timeout:60000});
      const id=Number(new URL(page.url()).pathname.split('/').pop());
      await page.getByText('材料已提交，请等待银行处理。',{exact:true}).waitFor({timeout:60000});
      const counts={};
      for (const kind of ['transactions','metrics']) {
        const response=await page.request.get(`http://127.0.0.1:5173/api/v1/tasks/${id}/${kind}`);
        if (response.status()!==200) throw Error('Result unavailable');
        counts[kind]=(await response.json()).length;
      }
      const response=await page.request.get(`http://127.0.0.1:5173/api/v1/reports/${id}`);
      if (response.status()!==200 || !(await response.json()).layers) throw Error('Report unavailable');
      if (counts.transactions!==3 || counts.metrics!==40) throw Error('Synthetic result mismatch');
      if (errors.length) throw Error('Browser runtime error');
      await page.screenshot({path:path.join(evidence,'20261031-progress.png'),fullPage:true});
      fs.writeFileSync(path.join(evidence,'20261031-web-pipeline.json'),JSON.stringify({
        source:'real_browser_and_live_mysql',task_id:id,...counts,report_read:true,
        borrower_conclusions_displayed:false,bank_report_ui_tested:false
      },null,2)+'\n');
      console.log('PASS: browser synthetic upload -> processing -> 3 transactions / 40 metrics / report API');
    }
  } finally { await browser.close(); }
})().catch(() => {console.error('FAIL: browser smoke (details suppressed)');process.exitCode=1;});
