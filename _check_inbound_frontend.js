/* 临时校验：把 inventory.html 里的内联 <script> 抽出来放进 node:vm，DOM 用桩，
   fetch 打真后端。验的是「表单攒出的数据对不对、真的发出去了、发完之后库里真的变了」。
   后端跑在 8002 的干净实例上（8001 上那个进程是旧的，不掺和）。 */
const fs = require('fs');
const vm = require('vm');
const cp = require('child_process');
const DIR = __dirname;

const BASE = 'http://127.0.0.1:8002';
const html = fs.readFileSync(DIR + '/frontend/inventory.html', 'utf8');
// 取最后一个无属性的 <script>（内联那段）；用懒惰正则从头匹配会抓到 head 里的 tailwind 配置
const tail = html.split('<script>').pop();
const src0 = tail.split('</script>')[0];
if (!src0.includes('function refreshPage')) { console.error('没找到内联脚本'); process.exit(1); }
// 脚本里 API 写死 8001，这里换成测试实例（只改这一处，其余原样）
const src = src0.replace(/var API='[^']*'/, `var API='${BASE}/api'`);
if (!src.includes(BASE)) { console.error('API 常量没替换成功'); process.exit(1); }

const dbq = (args) => cp.execSync(`python _dbq.py ${args}`, { cwd: DIR, encoding: 'utf8' });
const query = (sql) => JSON.parse(dbq(`query "${sql}"`));

const calls = [];
const els = {};
function mkEl(id) {
  return els[id] || (els[id] = {
    id, textContent: '', innerHTML: '', value: '', style: {}, className: '', disabled: false,
    classList: { add(){}, remove(){}, contains(){ return false; }, toggle(){} },
    addEventListener(){}, appendChild(){}, remove(){}, scrollIntoView(){},
  });
}
const doc = {
  documentElement: { classList: { add(){}, remove(){}, contains(){ return false; }, toggle(){} } },
  getElementById: mkEl, querySelectorAll: () => [],
  addEventListener: (ev, fn) => { doc._ready = fn; },
  createElement: () => mkEl('tmp' + Math.random()),
  body: { appendChild(){}, removeChild(){} },
};
const ctx = {
  console, setTimeout, clearTimeout, Math, JSON, parseInt, parseFloat, isNaN,
  document: doc,
  localStorage: { store: {}, getItem(k){ return this.store[k] ?? null; }, setItem(k,v){ this.store[k]=v; } },
  fetch: async (url, opt) => {
    calls.push({ url, method: (opt && opt.method) || 'GET', body: opt && opt.body ? JSON.parse(opt.body) : null });
    const r = await fetch(url, opt);
    return { json: async () => JSON.parse(await r.text()) };
  },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'inventory-inline.js' });

(async () => {
  let fail = 0;
  const ok = (c, msg) => { console.log((c ? '  ✅ ' : '  ❌ ') + msg); if (!c) fail++; };
  const rows = () => vm.runInContext('inRows.length', ctx);
  const waitFor = async (pred, what, ms = 8000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { if (pred()) return true; await new Promise(r => setTimeout(r, 50)); }
    console.log('   [debug] 等超时：' + what); return false;
  };

  const SNAPFILE = DIR + '/_snap_inbound.json';
  fs.writeFileSync(SNAPFILE, dbq('snap SKU001,SKU003'));
  const SNAP = JSON.parse(fs.readFileSync(SNAPFILE, 'utf8'));
  // 页面脚本是按需取元素的，桩得先建出来，不然拿到 undefined。
  // 内联 style 也要照 HTML 抄过来，否则面板的初始 display:none 就没了一—
  // toggleInbound 是靠读 style.display 判断当前状态的
  ['stockTable','totalSku','totalValue','lowCount','expiryPanel','slowPanel','replenishPanel',
   'replenishContent','repSource','inboundPanel','inboundRows','inboundTotal','inboundPreview',
   'inSupplier','inOperator','inboundSubmitBtn','recentInbound','toastContainer','themeIcon']
    .forEach(function (id) {
      const el = mkEl(id);
      const tag = (html.match(new RegExp('<[a-z]+[^>]*id="' + id + '"[^>]*>')) || [''])[0];
      if (/display\s*:\s*none/.test(tag)) el.style.display = 'none';
    });
  ok(els.inboundPanel.style.display === 'none', '桩对齐了页面初始状态：入库卡片默认藏着');

  try {
    console.log('=== 加载 ===');
    await doc._ready();
    await waitFor(() => vm.runInContext('stockItems.length', ctx) > 0, '库存拉回来');
    const n = vm.runInContext('stockItems.length', ctx);
    ok(n > 0, `拉到 ${n} 个 SKU`);
    await waitFor(() => els.recentInbound.innerHTML.includes('<table'), '入库记录渲染');
    ok(els.recentInbound.innerHTML.includes('<table'), '最近入库记录渲染成表格');
    ok(els.recentInbound.innerHTML.includes('期初'), '期初批次也在列表里');

    console.log('\n=== 表单：加行 / 删行 ===');
    ctx.toggleInbound();
    ok(els.inboundPanel.style.display === 'block', '点按钮展开了入库卡片');
    ok(rows() === 1, '默认自带一行');
    ctx.addInboundRow();
    ok(rows() === 2, '加一行 → 2 行');
    ok((els.inboundRows.innerHTML.match(/<select/g) || []).length === 2, 'DOM 里也是 2 个下拉');
    ctx.delInboundRow(0);
    ok(rows() === 1, '删一行 → 1 行');
    ok(els.inboundRows.innerHTML.includes('optgroup'), '下拉按类别分组');

    console.log('\n=== 选商品 → 带出进价 + 实时预览 ===');
    const b4 = SNAP.SKU003;
    els.inSupplier.value = '测试供应商';
    ctx.onPickSku(0, 'SKU003');
    ok(JSON.parse(vm.runInContext('JSON.stringify(inRows[0])', ctx)).unit_cost === b4.avg,
       `进价自动带出均价 ¥${b4.avg}`);
    ctx.setField(0, 'quantity', 5);
    ctx.setField(0, 'unit_cost', b4.avg);

    const wantStock = b4.stock + 5;
    const wantAvg = Number(((b4.stock * b4.avg + 5 * b4.avg) / wantStock).toFixed(2));
    const pv = els.inboundPreview.innerHTML;
    ok(pv.includes(`库存 <b>${b4.stock} → ${wantStock}</b>`), `预览显示库存 ${b4.stock} → ${wantStock}`);
    ok(pv.includes(`均价 <b>¥${b4.avg.toFixed(2)} → ¥${wantAvg.toFixed(2)}</b>`),
       `预览均价 ¥${b4.avg.toFixed(2)} → ¥${wantAvg.toFixed(2)}（与后端同一算式）`);
    ok(els.inboundTotal.textContent.includes('¥' + (5 * b4.avg).toFixed(2)), '合计：' + els.inboundTotal.textContent);

    console.log('\n=== 非法输入：本地拦下，不发请求 ===');
    ctx.setField(0, 'quantity', 0);
    calls.length = 0;
    await ctx.submitInbound();
    ok(calls.length === 0, '数量 0 时没发出任何请求');
    ctx.setField(0, 'quantity', 5);

    console.log('\n=== 提交：请求体 + 库里真的变了 ===');
    calls.length = 0;
    await ctx.submitInbound();
    const post = calls.filter(c => c.method === 'POST' && c.url.endsWith('/api/inbound'));
    ok(post.length === 1, `只发了一次 POST（拿到 ${post.length} 次）`);
    const body = post[0] && post[0].body;
    ok(body && body.lines.length === 1 && body.lines[0].sku_id === 'SKU003' && body.lines[0].quantity === 5,
       '请求体：' + JSON.stringify(body));
    ok(body.supplier_id === '测试供应商', '供应商带上了');

    const aft = query("SELECT current_stock, avg_cost FROM stock_snapshots WHERE sku_id='SKU003'")[0];
    ok(Number(aft.current_stock) === wantStock, `库里库存 → ${wantStock}（拿到 ${aft.current_stock}）`);
    ok(Number(aft.avg_cost) === wantAvg, `库里均价 ${aft.avg_cost}，与预览一致`);
    ok(rows() === 1 && vm.runInContext('inRows[0].sku_id', ctx) === '', '提交成功后表单清空');
    await waitFor(() => els.recentInbound.innerHTML.includes('豆腐猫砂'), '入库记录刷新');
    ok(els.recentInbound.innerHTML.includes('豆腐猫砂'), '最近入库记录里能看到刚录的这笔');

    console.log('\n=== 防重复提交（手抖点两下） ===');
    ctx.addInboundRow();
    ctx.onPickSku(1, 'SKU001');
    ctx.setField(1, 'quantity', 1);
    calls.length = 0;
    await Promise.all([ctx.submitInbound(), ctx.submitInbound()]);
    ok(calls.filter(c => c.method === 'POST').length === 1,
       `连点两次只提交一次（拿到 ${calls.filter(c => c.method === 'POST').length} 次）`);

    console.log('\n=== 名字反查 SKU（不信任 LLM 回传的 id） ===');
    ok(vm.runInContext("findSku('SKU003').name", ctx) === '豆腐猫砂', 'findSku 反查正确');
    ok(vm.runInContext("findSku('NOT-A-SKU')", ctx) === undefined, '对不上时返回 undefined → 调用处不渲染按钮');
    ok(vm.runInContext('stockItems.filter(function(s){return s.name===findSku(s.sku_id).name;}).length', ctx) > 0,
       '商品名在目录里是唯一的（可以安全按名字反查）');
  } finally {
    dbq(`restore "${SNAPFILE.replace(/\\/g, '/')}"`);
    fs.unlinkSync(SNAPFILE);
    const back = JSON.parse(dbq('snap SKU001,SKU003'));
    ok(Number(back.SKU003.stock) === SNAP.SKU003.stock && Object.keys(back.SKU003.batches).length === Object.keys(SNAP.SKU003.batches).length,
       `测试数据已还原（SKU003 库存回到 ${back.SKU003.stock}）`);
  }

  console.log(fail === 0 ? '\n全部通过' : `\n${fail} 项失败`);
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error(e); process.exit(1); });
