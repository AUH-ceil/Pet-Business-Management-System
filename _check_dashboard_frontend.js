/* 临时校验脚本：把真的 dashboard.js 放进 node:vm 里跑，DOM 用桩，
   但 fetch 打真后端。验的是"前端有没有真的按 period 去问、拿回来有没有真的画"。 */
const fs = require('fs');
const vm = require('vm');

const calls = [];
const els = {};
function mkEl(id) {
  return els[id] || (els[id] = {
    id, textContent: '', innerHTML: '', style: {}, className: '',
    classList: { add(){}, remove(){}, contains(){ return false; } },
    addEventListener(){}, appendChild(){}, remove(){}, scrollIntoView(){},
    getContext(){ return {}; },
  });
}
const doc = {
  documentElement: { classList: { add(){}, remove(){}, contains(){ return false; }, toggle(){} } },
  getElementById: (id) => mkEl(id),
  querySelectorAll: () => [],
  addEventListener: (ev, fn) => { doc._ready = fn; },
  createElement: () => mkEl('tmp'),
  body: { appendChild(){}, removeChild(){} },
};

const chartData = { labels: [], datasets: [{ label: '', data: [], borderColor: '', backgroundColor: '' }] };
function FakeChart() { return { data: chartData, options: { plugins:{legend:{labels:{}}}, scales:{y:{grid:{},ticks:{}},x:{ticks:{}}} }, update(){} }; }

const ctx = {
  console,
  setTimeout, clearTimeout,
  document: doc,
  localStorage: { store: {}, getItem(k){ return this.store[k] ?? null; }, setItem(k,v){ this.store[k]=v; } },
  navigator: { clipboard: { writeText: async()=>{} } },
  Chart: FakeChart,
  fetch: async (url) => {
    calls.push(url);
    // 前端现在用同源相对路径 /api/...，Node 的 fetch 不认相对地址，
    // 这里补上后端 origin。同时这也是断言"页面里没有写死主机名"的抓手。
    const abs = url.startsWith('/') ? 'http://127.0.0.1:8001' + url : url;
    const r = await fetch(abs);
    const t = await r.text();
    return { json: async () => JSON.parse(t) };
  },
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__dirname + '/frontend/js/dashboard.js', 'utf8'), ctx, { filename: 'dashboard.js' });

(async () => {
  let fail = 0;
  const ok = (cond, msg) => { console.log((cond ? '  ✅ ' : '  ❌ ') + msg); if (!cond) fail++; };
  // refreshDashboard 是异步的，等它把我们关心的那一步做完再断言，
  // 别拿定时器去赌（第一次写这个就赌输了）
  const waitFor = async (pred, what, ms = 8000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { if (pred()) return true; await new Promise(r => setTimeout(r, 50)); }
    console.log('   [debug] 等超时：' + what);
    return false;
  };

  console.log('=== 初始加载（period=today）===');
  await doc._ready();
  // 部署陷阱回归：前端必须发同源相对路径。写死 http://127.0.0.1:8001/api 的话，
  // 服务器上跑起来后，外面的浏览器会去请求访问者自己的机器，页面全空但不报错。
  ok(calls.length > 0 && calls.every(u => u.startsWith('/')), '所有请求都是同源相对路径，没写死主机名');
  ok(!calls.some(u => /^https?:\/\//.test(u)), '没有任何绝对 URL（' + calls.filter(u => /^https?:\/\//.test(u)).join(',') + '）');

  ok(calls.some(u => u.includes('/dashboard/summary?period=today')), 'summary 带了 period=today');
  ok(calls.some(u => u.includes('/dashboard/trend?period=today')), 'trend 带了 period=today');
  ok(calls.some(u => u.includes('/dashboard/top-products?period=today')), 'top-products 带了 period=today');
  ok(els.monthlyPanel.style.display === 'none', '非"近一年"时月度表是隐藏的');
  ok(chartData.datasets[0].data.length === 7, '今日趋势画了 7 个点（拿到 ' + chartData.datasets[0].data.length + '）');
  ok(els.kpiRevenueLabel.textContent === '今日营收', 'KPI 标题 = 今日营收（拿到 ' + els.kpiRevenueLabel.textContent + '）');
  console.log('   今日营收显示：' + els.kpiRevenue.textContent + '，订单 ' + els.kpiOrders.textContent);

  console.log('\n=== 切到「近一年」===');
  calls.length = 0;
  ctx.switchPeriod('year', mkEl('btnYear'));
  await waitFor(() => els.monthlyTableBody && els.monthlyTableBody.innerHTML.includes('<tr '), '月度表渲染完');
  console.log('   [debug] currentPeriod =', vm.runInContext('currentPeriod', ctx));
  ok(calls.every(u => !u.includes('period=today')), '切周期后不再请求 today');
  ok(calls.some(u => u.includes('/dashboard/monthly?months=12')), '拉取了月度明细');
  ok(els.monthlyPanel.style.display === 'block', '月度表显示出来了');
  ok(els.kpiRevenueLabel.textContent === '近一年营收', 'KPI 标题跟着变成 近一年营收（拿到 ' + els.kpiRevenueLabel.textContent + '）');

  const rows = (els.monthlyTableBody.innerHTML.match(/<tr /g) || []).length;
  ok(rows === 12, '月度表 12 行（拿到 ' + rows + '）');
  ok(!els.monthlyTableBody.innerHTML.includes('NaN'), '表里没有 NaN');
  ok(!els.monthlyTableBody.innerHTML.includes('undefined'), '表里没有 undefined');
  ok(els.monthlyTableBody.innerHTML.includes('本月进行中'), '当月标注了"本月进行中"，没给假的环比');
  ok(els.monthlyRange.textContent.includes('~'), '表头显示了区间：' + els.monthlyRange.textContent);

  const labels = chartData.labels;
  ok(labels.length === 12, '折线图 12 个点（拿到 ' + labels.length + '）');
  ok(labels.every(l => /\d+月/.test(l)), '12 个点全是月份：' + labels.join(','));

  console.log('\n=== 切图表：营收 → 订单量 ===');
  const revSnap = chartData.datasets[0].data.slice();
  ctx.switchChart('orders', mkEl('btnOrders'));
  await new Promise(r => setTimeout(r, 50));
  const ordSnap = chartData.datasets[0].data.slice();
  ok(chartData.datasets[0].label === '订单量', '图例变成了"订单量"');
  ok(JSON.stringify(revSnap) !== JSON.stringify(ordSnap), '换成了订单数组，不是同一份营收数据');
  const sumRev = revSnap.reduce((a,b)=>a+b,0), sumOrd = ordSnap.reduce((a,b)=>a+b,0);
  ok(sumOrd > 100 && sumOrd < 100000, '订单量合计看着像订单数而不是金额：' + sumOrd);

  console.log('\n=== 自然区间：本月必须是 1 号到月末，不是滚动 30 天 ===');
  calls.length = 0;
  ctx.switchPeriod('month', mkEl('btnMonth'));
  {
    const d = new Date();
    const lastDay = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    const wantFirst = (d.getMonth()+1) + '/1';
    // 等本次刷新生效。条件必须专指"本月"，用 includes('~') 会被上一步"近一年"的
    // 标签直接满足、根本不等——这个坑刚踩过一次
    await waitFor(() => chartData.labels[0] === wantFirst, '本月数据到位');
    const L = chartData.labels;
    const today = d.getDate();
    ok(chartData.labels.length === lastDay,
       '本月桶数 = 当月天数 ' + lastDay + '（拿到 ' + L.length + '）');
    ok(L[0] === (d.getMonth()+1) + '/1', '第一个点是 ' + (d.getMonth()+1) + '/1（拿到 ' + L[0] + '）');
    ok(L[L.length-1] === (d.getMonth()+1) + '/' + lastDay,
       '最后一个点是 ' + (d.getMonth()+1) + '/' + lastDay + '（拿到 ' + L[L.length-1] + '）');
    // 今天之后的日子必须是 0，不能凭空有数
    const future = chartData.datasets[0].data.slice(today);
    ok(future.length > 0 && future.every(v => v === 0),
       '今天之后的 ' + future.length + ' 天全是 0（' + JSON.stringify(future.slice(0,5)) + '…）');
    ok(chartData.datasets[0].data.slice(0, today).some(v => v > 0),
       '已过去的日子里有真实数据');
    console.log('   图表标题区间：' + els.trendRange.textContent);
  }

  console.log('\n=== 切回「今日」应重新拉数据 ===');
  calls.length = 0;
  ctx.switchPeriod('today', mkEl('btnToday'));
  await waitFor(() => calls.some(u => u.includes('period=today')), '切回今日的请求');
  await waitFor(() => els.kpiRevenueLabel.textContent === '今日营收', 'KPI 标题切回今日');
  ok(calls.some(u => u.includes('period=today')), '切回今日确实重新请求了');
  ok(els.monthlyPanel.style.display === 'none', '月度表又收起来了');

  console.log(fail === 0 ? '\n全部通过' : `\n${fail} 项失败`);
  process.exit(fail === 0 ? 0 : 1);
})();
