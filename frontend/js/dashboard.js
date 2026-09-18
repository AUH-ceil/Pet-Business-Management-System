/* ============================================================
   petstore_agent/frontend/js/dashboard.js
   经营看板 — 经营数据来自后端（日报表 + 今日实时）
   ============================================================ */
const DARK = localStorage.getItem('darkMode') === 'true';
if (DARK) document.documentElement.classList.add('dark');

const DASH_API_BASE = '/api';   // 同源相对路径。原先写死成 http://127.0.0.1:8001/api，部署到服务器后
// 用浏览器远程访问时，这个地址指的是访问者自己的机器，不是服务器。
let trendChartInst = null;

// ====== 经营数据的口径 ======
// 以前这个页面是拿 localStorage.petstore_sales 自己算营收的，那份账只留最近
// 100 单、换个浏览器就没了，永远凑不出一年。现在一律问后端：
//   昨天及以前 → daily_metrics 日报表（/api/dashboard/*）
//   今天       → 实时算出库记录（后端内部处理，前端不用管）
// localStorage 那套降级成离线兜底，只在后端连不上时顶上。
let currentPeriod = 'today';                 // today | week | month | year
let trendData = { labels: [], revenue: [], orders: [] };
let chartMode = 'revenue';
var PERIOD_LABEL = { today: '今日', week: '本周', month: '本月', year: '近一年' };

// ====== 库存统一口径 ======
// 看板以前是拿 localStorage 快照自己再算一遍（阈值 ≤10），和库存先知的
// replenish_point 属于两套规则，数字必然对不上。现在统一从后端取，
// 本地快照只在后端不可用时兜底。
let LIVE_STOCK = null;
async function loadLiveStock() {
  if (LIVE_STOCK) return LIVE_STOCK;
  try {
    var r = await fetch(DASH_API_BASE + '/stock/all');
    var d = await r.json();
    if (d && d.success) { LIVE_STOCK = d.data || []; return LIVE_STOCK; }
  } catch(e) {}
  return null;   // 后端连不上 → 调用方退回本地快照
}

// ====== 初始化 ======
document.addEventListener('DOMContentLoaded', async function() {
  updateThemeIcon();
  safeCall('initTrendChart', initTrendChart);
  await refreshDashboard();
});

// ====== 主题 ======
function toggleTheme() {
  var d = !document.documentElement.classList.contains('dark');
  document.documentElement.classList.toggle('dark', d);
  localStorage.setItem('darkMode', d);
  updateThemeIcon();
  if (trendChartInst) updateTrendChartColors();
}
function updateThemeIcon() {
  var el = document.getElementById('themeIcon');
  if (el) el.className = document.documentElement.classList.contains('dark') ? 'fas fa-sun' : 'fas fa-moon';
}

// ====== 安全调用 ======
function safeCall(name, fn) {
  try { fn(); } catch(e) { console.error(name + ' 失败:', e); }
}
function $(id) { return document.getElementById(id); }
function text(id, val) { var el = $(id); if (el) el.textContent = val; }
function html(id, val) { var el = $(id); if (el) el.innerHTML = val; }

// ====== 图表 ======
function initTrendChart() {
  var ctx = $('trendChart');
  if (!ctx || typeof Chart === 'undefined') return;
  var dark = document.documentElement.classList.contains('dark');
  trendChartInst = new Chart(ctx.getContext('2d'), {
    type: 'line',
    data: { labels: [], datasets: [{ label: '营收 (¥)', data: [], borderColor: '#f9973e', backgroundColor: 'rgba(249,151,62,0.1)', fill: true, tension: 0.4, pointRadius: 4, borderWidth: 2.5 }] },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { labels: { color: dark ? '#94a3b8' : '#64748b' } } },
      scales: {
        y: { beginAtZero: true, grid: { color: dark ? '#334155' : '#e2e8f0' }, ticks: { color: dark ? '#94a3b8' : '#64748b' } },
        x: { grid: { display: false }, ticks: { color: dark ? '#94a3b8' : '#64748b' } }
      }
    }
  });
}
function updateTrendChartColors() {
  if (!trendChartInst) return;
  var dark = document.documentElement.classList.contains('dark');
  var c = dark ? '#94a3b8' : '#64748b';
  var g = dark ? '#334155' : '#e2e8f0';
  trendChartInst.options.plugins.legend.labels.color = c;
  trendChartInst.options.scales.y.grid.color = g;
  trendChartInst.options.scales.y.ticks.color = c;
  trendChartInst.options.scales.x.ticks.color = c;
  trendChartInst.update();
}
function updateTrendChart(labels, data) {
  if (!trendChartInst) return;
  trendChartInst.data.labels = labels;
  trendChartInst.data.datasets[0].data = data;
  trendChartInst.update();
}

// ====== 刷新数据 ======
async function refreshDashboard() {
  hideLoading();

  // 1. 读 localStorage —— 只作离线兜底
  var salesLog = [];
  var stockData = {};
  try {
    salesLog = JSON.parse(localStorage.getItem('petstore_sales') || '[]');
    stockData = JSON.parse(localStorage.getItem('petstore_stock') || '{}');
  } catch(e) {}

  // 3. 算库存（优先真实库存；低库存口径 = 库存先知的 replenish_point）
  var live = await loadLiveStock();
  var totalStock = 0, lowCount = 0;
  if (live) {
    live.forEach(function(i) {
      if (i.current_stock > 0) totalStock += i.current_stock;
      // 注意：这里不加 >0 判断，与后端 /api/stock/alerts 逐字一致（售罄同样要预警）
      if (i.current_stock <= i.replenish_point) lowCount++;
    });
  } else {
    for (var cat in stockData) {
      for (var id in stockData[cat]) {
        var q = stockData[cat][id];
        if (q > 0) totalStock += q;
        if (q <= 10 && q > 0) lowCount++;
      }
    }
  }

  // 4. 库存预警
  var nameMap = {};
  try { nameMap = JSON.parse(localStorage.getItem('petstore_products') || '{}'); } catch(e) {}
  var warnings = [];
  if (live) {
    live.forEach(function(i) {
      if (i.current_stock <= i.replenish_point) {
        warnings.push({
          name: i.name,
          stock: i.current_stock,
          severity: i.current_stock <= 3 ? 'urgent' : 'warning',
          note: i.current_stock <= 3 ? '急需补货' : '低于补货点'
        });
      }
    });
  } else {
    for (var cat in stockData) {
      for (var id in stockData[cat]) {
        var q = stockData[cat][id];
        if (q <= 10 && q > 0) {
          warnings.push({
            name: (nameMap[id] && nameMap[id].name) || id,
            stock: q,
            severity: q <= 3 ? 'urgent' : 'warning',
            note: q <= 3 ? '急需补货' : '库存偏低'
          });
        }
      }
    }
  }
  warnings.sort(function(a,b){ return a.stock - b.stock; });

  // ====== 并行拉取后端数据 ======
  var groomData = null, daycareData = null, healthData = null, custStats = null;
  var dashStats = null, dashTrend = null, dashTop = null;
  try {
    var results = await Promise.allSettled([
      fetch(DASH_API_BASE + '/grooming/today').then(function(r){ return r.json(); }),
      fetch(DASH_API_BASE + '/daycare/today').then(function(r){ return r.json(); }),
      fetch(DASH_API_BASE + '/health/alerts').then(function(r){ return r.json(); }),
      fetch(DASH_API_BASE + '/customers/stats').then(function(r){ return r.json(); }),
      fetch(DASH_API_BASE + '/dashboard/summary?period=' + currentPeriod).then(function(r){ return r.json(); }),
      fetch(DASH_API_BASE + '/dashboard/trend?period=' + currentPeriod).then(function(r){ return r.json(); }),
      fetch(DASH_API_BASE + '/dashboard/top-products?period=' + currentPeriod).then(function(r){ return r.json(); }),
    ]);
    groomData = results[0].status === 'fulfilled' ? results[0].value : null;
    daycareData = results[1].status === 'fulfilled' ? results[1].value : null;
    healthData = results[2].status === 'fulfilled' ? results[2].value : null;
    custStats = results[3].status === 'fulfilled' ? results[3].value : null;
    dashStats = results[4].status === 'fulfilled' ? results[4].value : null;
    dashTrend = results[5].status === 'fulfilled' ? results[5].value : null;
    dashTop   = results[6].status === 'fulfilled' ? results[6].value : null;
  } catch(e) {}
  if (dashStats && !dashStats.success) dashStats = null;
  if (dashTrend && !dashTrend.success) dashTrend = null;
  if (dashTop   && !dashTop.success)   dashTop   = null;

  // ====== 渲染 ======
  // KPI — 营收/订单：后端优先，连不上才退回本地那份账
  var revenue = 0, orders = 0, fromBackend = false;
  if (dashStats) {
    revenue = dashStats.data.revenue || 0;
    orders = dashStats.data.orders || 0;
    fromBackend = true;
  } else {
    var today = new Date().toISOString().slice(0, 10);
    var todaySales = salesLog.filter(function(s) { return s.time && s.time.startsWith(today); });
    revenue = todaySales.reduce(function(sum, s) { return sum + (s.total || 0); }, 0);
    orders = todaySales.length;
  }
  // 卡片标题跟着 period 走——否则切到"近一年"，标题还写"今日营收"，
  // 数字却是全年的，等于 UI 在撒谎
  text('kpiRevenueLabel', PERIOD_LABEL[currentPeriod] + '营收');
  text('kpiOrdersLabel', PERIOD_LABEL[currentPeriod] + '订单');
  text('kpiRevenue', revenue > 0 ? '¥' + revenue.toLocaleString() : '¥0');
  text('kpiOrders', orders);
  // 退回本地账时必须说出来，不能让人以为看到的是完整的经营数据
  if (!fromBackend) showToast2('后端不可用，营收/订单已退回本地记录（仅最近100单）', 'warn');
  text('kpiStockTotal', totalStock);
  text('kpiLowStock', lowCount);

  // KPI — 洗护 & 托管（来自真实API）
  var groomingTotal = 0, groomingPending = 0;
  if (groomData && groomData.success) {
    groomingTotal = groomData.total || 0;
    groomingPending = groomData.pending || 0;
  }
  var daycareActive = 0;
  if (daycareData && daycareData.success) {
    daycareActive = (daycareData.data || []).length;
  }
  text('kpiGrooming', groomingTotal);
  text('kpiGroomingPending', groomingPending);
  text('kpiDaycareActive', daycareActive);

  // KPI — 客户 & 健康（来自真实API）
  var followUpCount = 0, churnCount = 0, custRiskCount = 0;
  if (healthData && healthData.success) {
    followUpCount = (healthData.follow_ups || []).length;
    churnCount = (healthData.retention_risks || []).length;
    custRiskCount = followUpCount + churnCount;
  }
  text('kpiCustomerRisks', custRiskCount);
  text('kpiFollowUp', followUpCount);
  text('kpiChurn', churnCount);

  // 趋势图：后端返回的 labels 是补过零的定长数组（7 / 30 / 12 个点），
  // 后端连不上才退回"本地近 7 天"
  if (dashTrend) {
    trendData = { labels: dashTrend.data.labels || [],
                  revenue: dashTrend.data.revenue || [],
                  orders: dashTrend.data.orders || [] };
    // 图在画哪一段，直接写在标题上。"本周/本月"是自然周/自然月（未来的日子是 0），
    // "今日"那张画的是近 7 天背景——不写出来没人分得清
    text('trendRange', dashTrend.data.range || '');
  } else {
    var fbLabels = [], fbRev = [], fbCnt = [];
    for (var i = 6; i >= 0; i--) {
      var d = new Date(); d.setDate(d.getDate() - i);
      var ds = d.toISOString().slice(0,10);
      var daySales = salesLog.filter(function(s) { return s.time && s.time.startsWith(ds); });
      fbLabels.push((d.getMonth()+1) + '/' + d.getDate());
      fbRev.push(daySales.reduce(function(sum,s){ return sum + (s.total||0); }, 0));
      fbCnt.push(daySales.length);
    }
    trendData = { labels: fbLabels, revenue: fbRev, orders: fbCnt };
    text('trendRange', '近 7 天（本地）');
  }
  drawTrendChart();

  // 热销TOP5
  var topList = null;
  if (dashTop) {
    topList = dashTop.data || [];
  } else {
    var soldMap = {};
    salesLog.forEach(function(s) {
      (s.items || []).forEach(function(it) {
        if (!soldMap[it.name]) soldMap[it.name] = { name: it.name, sold_qty: 0, revenue: 0 };
        soldMap[it.name].sold_qty += (it.qty || 0);
        soldMap[it.name].revenue += (it.subtotal || 0);
      });
    });
    topList = Object.values(soldMap).sort(function(a,b){ return b.revenue - a.revenue; }).slice(0,5);
  }
  var topHTML = '';
  if (topList.length > 0) {
    topList.forEach(function(p, i) {
      var cls = i === 0 ? 'top1' : i === 1 ? 'top2' : i === 2 ? 'top3' : 'top';
      topHTML += '<li><span class="rank-num ' + cls + '">' + (i+1) + '</span><span style="flex:1;">' + p.name + '</span><span style="color:var(--text-muted);">售 ' + p.sold_qty + ' 件</span><span style="font-weight:600;">¥' + (p.revenue||0).toLocaleString() + '</span></li>';
    });
  } else {
    topHTML = '<li class="empty-state"><p>暂无销售数据</p></li>';
  }
  html('top5List', topHTML);

  // 月度明细表：只在「近一年」下出现
  await renderMonthlyTable();

  // 库存预警
  var warnHTML = '';
  if (warnings.length > 0) {
    warnings.forEach(function(w) {
      warnHTML += '<div class="alert-item"><div class="alert-icon ' + (w.severity === 'urgent' ? 'danger' : 'warning') + '"><i class="fas fa-exclamation"></i></div><div class="alert-text"><div class="title">' + w.name + '</div><div class="desc">剩余 ' + w.stock + ' 件 · ' + w.note + '</div></div></div>';
    });
  } else {
    warnHTML = '<div style="font-size:13px;color:var(--success);">库存状态良好</div>';
  }
  html('stockWarnings', warnHTML);

  // 客户运营（来自真实API）
  if (custStats && custStats.success) {
    var cs = custStats.data;
    text('totalCustomers', cs.total || 0);
    text('repeatRate', (cs.repeat_rate || 0) + '%');
    text('newCustomerBadge', (cs.new_this_month || 0) + ' 新客');
  } else {
    text('totalCustomers', '--');
    text('repeatRate', '--');
    text('newCustomerBadge', '--');
  }

  // 流失客户列表
  renderCustomerRetention();

  // 洗护排班（来自真实API）
  renderGroomerSchedule(groomData);

  // 托管（来自真实API）
  renderDaycareStatus(daycareData);

  // 健康告警（来自真实API）
  renderHealthAlerts(healthData);

  // RAG 推荐引擎
  renderRAG(salesLog);
}

// ====== 洗护排班渲染 ======
function renderGroomerSchedule(groomData) {
  var container = document.getElementById('groomerSchedule');
  if (!groomData || !groomData.success || !groomData.groomers || groomData.groomers.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>今日暂无洗护预约</p></div>';
    return;
  }

  var statusLabel = { '已预约': '⏳', '进行中': '🔵', '已完成': '✅', '已取消': '❌' };
  var html = '';
  groomData.groomers.forEach(function(g) {
    var apptCount = g.appointments.length;
    html += '<div style="margin-bottom:8px;padding:10px;background:var(--bg-input);border-radius:8px;">';
    html += '<div style="display:flex;justify-content:space-between;font-size:14px;margin-bottom:6px;">';
    html += '<span style="font-weight:600;"><i class="fas fa-user-check mr-1" style="color:var(--accent);"></i>' + g.name + '</span>';
    html += '<span style="color:var(--text-muted);font-size:12px;">' + apptCount + ' 单</span></div>';

    if (apptCount === 0) {
      html += '<div style="font-size:12px;color:var(--text-muted);padding:4px 0;">暂无预约</div>';
    } else {
      g.appointments.forEach(function(a) {
        html += '<div style="font-size:12px;padding:4px 0;display:flex;justify-content:space-between;align-items:center;color:var(--text-secondary);">';
        html += '<span><b>' + a.time + '</b> ' + a.pet_name + '（' + a.service_type + '）</span>';
        html += '<span style="font-size:11px;">' + (statusLabel[a.status] || '⏳') + a.status + '</span>';
        html += '</div>';
        if (a.pet_notes) {
          html += '<div style="font-size:11px;color:var(--text-muted);padding:2px 0 4px 14px;font-style:italic;">💡 ' + a.pet_notes + '</div>';
        }
      });
    }
    html += '</div>';
  });
  container.innerHTML = html;
}

// ====== 托管状态渲染 ======
function renderDaycareStatus(daycareData) {
  var container = document.getElementById('daycareStatus');
  if (!daycareData || !daycareData.success || !daycareData.data || daycareData.data.length === 0) {
    container.innerHTML = '<div class="empty-state"><p>暂无托管宠物</p></div>';
    return;
  }

  var typeLabel = { 'daycare': '日托', 'boarding': '寄养', 'playing': '玩耍' };
  var statusClass = { 'playing': 'daycare-status-playing', 'resting': 'daycare-status-boarding', 'boarding': 'daycare-status-boarding' };
  var html = '';
  daycareData.data.forEach(function(d) {
    html += '<div class="daycare-card ' + (statusClass[d.status] || '') + '" style="margin-bottom:8px;">';
    html += '<div class="pet-header"><span class="pet-name">' + d.pet_name + '（' + (d.breed || '') + '）</span>';
    html += '<span class="staff-badge"><i class="fas fa-user-circle mr-1"></i>' + (d.staff || '') + '</span></div>';
    html += '<div class="detail-row"><span>' + (d.owner_name || '') + '</span>';
    html += '<span>' + (typeLabel[d.daycare_type] || d.daycare_type) + ' · ' + (d.duration || '') + '</span>';
    html += '<span style="font-size:11px;color:var(--text-muted);">' + (d.checkin_time || '').slice(11,16) + '</span></div>';
    if (d.notes) {
      html += '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">📝 ' + d.notes + '</div>';
    }
    html += '</div>';
  });
  container.innerHTML = html;
}

// ====== 健康告警渲染 ======
function renderHealthAlerts(healthData) {
  var container = document.getElementById('healthAlerts');
  if (!healthData || !healthData.success) {
    container.innerHTML = '<div class="empty-state"><p>暂无待处理提醒</p></div>';
    return;
  }

  var html = '';
  // 回访提醒
  var followUps = healthData.follow_ups || [];
  followUps.forEach(function(f) {
    html += '<div class="alert-item"><div class="alert-icon info"><i class="fas fa-phone"></i></div>';
    html += '<div class="alert-text"><div class="title">"' + f.pet_name + '" 售出第' + (f.days_after_sale || '?') + '天</div>';
    html += '<div class="desc">' + (f.action || '需要回访确认适应情况') + '</div></div></div>';
  });
  // 隔离提醒
  var isolations = healthData.isolation_alerts || [];
  isolations.forEach(function(item) {
    html += '<div class="alert-item"><div class="alert-icon warning"><i class="fas fa-shield-halved"></i></div>';
    html += '<div class="alert-text"><div class="title">"' + item.pet_name + '" 隔离检查</div>';
    html += '<div class="desc">' + (item.message || '需要确认健康状态') + '</div></div></div>';
  });
  // 流失风险
  var risks = healthData.retention_risks || [];
  risks.forEach(function(r) {
    html += '<div class="alert-item"><div class="alert-icon danger"><i class="fas fa-user-clock"></i></div>';
    html += '<div class="alert-text"><div class="title">' + (r.customer_name || '') + ' · ' + (r.pet_name || '') + '</div>';
    html += '<div class="desc">' + (r.reason || '') + ' · ' + (r.suggestion || '') + '</div></div></div>';
  });

  container.innerHTML = html || '<div class="empty-state"><p>暂无待处理提醒</p></div>';
}

// ====== 流失客户列表（从API拉） ======
async function renderCustomerRetention() {
  var container = document.getElementById('customerRetentionList');
  try {
    var resp = await fetch(DASH_API_BASE + '/customers/retention-suggestions');
    var data = await resp.json();
    if (data.success && data.items && data.items.length > 0) {
      container.innerHTML = data.items.map(function(c) {
        return '<div class="alert-item"><div class="alert-icon warning"><i class="fas fa-user-clock"></i></div><div class="alert-text"><div class="title">' + c.name + ' · ' + c.pet_name + '（' + c.pet_breed + '）</div><div class="desc">' + c.reason + ' · ' + c.suggestion + '</div></div></div>';
      }).join('');
    } else {
      container.innerHTML = '<div class="empty-state"><p>暂无流失预警客户</p></div>';
    }
  } catch(e) {
    container.innerHTML = '<div class="empty-state"><p>暂无流失预警客户</p></div>';
  }
}

// ====== RAG 智能推荐 ======
function renderRAG(salesLog) {
  // 统计商品共现关系（同一单里一起买的）
  var cooccur = {}; // "A|B" → count
  salesLog.forEach(function(s) {
    var names = (s.items || []).map(function(it) { return it.name; });
    for (var i = 0; i < names.length; i++) {
      for (var j = i + 1; j < names.length; j++) {
        var key = names[i] < names[j] ? names[i] + '|' + names[j] : names[j] + '|' + names[i];
        cooccur[key] = (cooccur[key] || 0) + 1;
      }
    }
  });

  // 取 Top 3 共现对
  var pairs = Object.entries(cooccur)
    .sort(function(a, b) { return b[1] - a[1]; })
    .slice(0, 3);

  var container = document.getElementById('ragRecommendations');
  if (!container) return;

  if (pairs.length === 0) {
    container.innerHTML = '<div class="empty-state" style="grid-column:1/-1;"><p>收银台结算后，RAG引擎自动分析消费模式生成推荐</p></div>';
    return;
  }

  var maxCount = pairs[0][1];
  container.innerHTML = pairs.map(function(p, idx) {
    var items = p[0].split('|');
    var similarity = Math.round((p[1] / maxCount) * 100);
    return '<div style="padding:16px;background:var(--bg-input);border-radius:10px;border-left:4px solid var(--accent);">'
      + '<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">'
      + '<i class="fas fa-vector-square mr-1" style="color:var(--accent);"></i>'
      + '向量相似度 <b style="color:var(--accent);">' + similarity + '%</b>（共现 ' + p[1] + ' 次）'
      + '</div>'
      + '<div style="font-size:14px;line-height:1.6;">'
      + '买了 <b style="color:var(--info);">' + items[0] + '</b> 的顾客<br>也买了 <b style="color:var(--success);">' + items[1] + '</b>'
      + '</div>'
      + '<div style="font-size:12px;color:var(--text-muted);margin-top:4px;">'
      + '→ Qdrant 余弦匹配：两商品购买客群画像相似度 ' + similarity + '%'
      + '</div>'
      + '</div>';
  }).join('');
}

// ====== 加载状态 ======
function showLoading() { var el = $('loadingOverlay'); if (el) el.style.display = 'flex'; }
function hideLoading() { var el = $('loadingOverlay'); if (el) el.style.display = 'none'; }

// ====== Toast ======
function showToast2(msg, type) {
  var c = document.getElementById('toastContainer');
  if (!c) return;
  var icons = { success:'fa-check-circle', error:'fa-times-circle', warn:'fa-exclamation-triangle' };
  var t = document.createElement('div');
  t.className = 'toast ' + (type || 'success');
  t.innerHTML = '<i class="fas ' + (icons[type]||icons.info) + '"></i> ' + msg;
  c.appendChild(t);
  setTimeout(function(){ t.remove(); }, 2500);
}

// ====== AI 补货分析 ======
async function runReplenishAnalysis() {
  var panel = document.getElementById('replenishPanel');
  var content = document.getElementById('replenishContent');
  panel.style.display = 'block';
  content.innerHTML = '<div class="empty-state"><div class="spinner spinner-lg"></div><p style="margin-top:8px;">RAG检索 + LLM分析中...</p></div>';
  document.getElementById('replenishSource').textContent = '分析中...';

  // 1. 收集数据：库存、销售记录、RAG顾客偏好
  var stockData = {};
  try { stockData = JSON.parse(localStorage.getItem('petstore_stock') || '{}'); } catch(e) {}
  var salesLog = [];
  try { salesLog = JSON.parse(localStorage.getItem('petstore_sales') || '[]'); } catch(e) {}
  var custHistory = {};
  try { custHistory = JSON.parse(localStorage.getItem('cust_history') || '{}'); } catch(e) {}
  var nameMap = {};
  try { nameMap = JSON.parse(localStorage.getItem('petstore_products') || '{}'); } catch(e) {}

  // 2. 构建低库存清单（口径同库存先知：低于补货点）
  var live = await loadLiveStock();
  var lowStock = [];
  if (live) {
    live.forEach(function(i) {
      if (i.current_stock <= i.replenish_point) {
        lowStock.push({ name: i.name, stock: i.current_stock, category: i.category });
      }
    });
  } else {
    for (var cat in stockData) {
      for (var id in stockData[cat]) {
        var q = stockData[cat][id];
        var info = nameMap[id] || {};
        if (q <= 10 && q > 0) {
          lowStock.push({ name: info.name || id, stock: q, category: info.category || cat });
        }
      }
    }
  }
  lowStock.sort(function(a,b){ return a.stock - b.stock; });

  // 3. 销售趋势（近14天各商品销量）
  var soldMap = {};
  salesLog.forEach(function(s) {
    (s.items || []).forEach(function(it) {
      if (!soldMap[it.name]) soldMap[it.name] = { name: it.name, qty: 0, amount: 0 };
      soldMap[it.name].qty += it.qty;
      soldMap[it.name].amount += (it.subtotal || 0);
    });
  });
  var hotItems = Object.values(soldMap).sort(function(a,b){ return b.qty - a.qty; }).slice(0, 8);

  // 4. RAG：顾客偏好（什么品类最受欢迎）
  var categoryPreference = {};
  var allPurchased = [];
  for (var phone in custHistory) {
    var profile = custHistory[phone];
    profile.purchases.forEach(function(s) {
      s.items.forEach(function(it) {
        allPurchased.push(it.name);
      });
    });
  }
  // 简单统计品类倾向
  allPurchased.forEach(function(name) {
    if (name.includes('猫')) categoryPreference['猫用'] = (categoryPreference['猫用'] || 0) + 1;
    if (name.includes('犬')) categoryPreference['狗用'] = (categoryPreference['狗用'] || 0) + 1;
    if (name.includes('零食') || name.includes('罐头') || name.includes('冻干')) categoryPreference['零食'] = (categoryPreference['零食'] || 0) + 1;
    if (name.includes('猫砂') || name.includes('尿垫') || name.includes('碗')) categoryPreference['用品'] = (categoryPreference['用品'] || 0) + 1;
  });

  // 5. 调用 LLM（失败则用规则引擎）
  var llmResult = null;
  try {
    var resp = await fetch('/api/replenish/analyze', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        low_stock: lowStock,
        hot_items: hotItems,
        category_preference: categoryPreference,
        total_sales_count: salesLog.length,
      }),
    });
    var data = await resp.json();
    if (data.success) llmResult = data.data;
  } catch(e) {}

  // 6. 渲染结果
  document.getElementById('replenishSource').textContent = llmResult ? 'RAG + DeepSeek' : 'RAG + 规则引擎';

  var html = '';

  if (llmResult) {
    // LLM 结果
    html += '<div style="background:var(--info-light);padding:16px;border-radius:10px;margin-bottom:12px;">';
    html += '<div style="font-size:13px;font-weight:600;color:var(--info);margin-bottom:8px;"><i class="fas fa-robot mr-1"></i>DeepSeek 分析</div>';
    html += '<div style="font-size:14px;line-height:1.8;color:var(--text-primary);">' + (llmResult.analysis || llmResult.recommendation || '').replace(/\n/g, '<br>') + '</div>';
    html += '</div>';

    if (llmResult.urgent_items && llmResult.urgent_items.length > 0) {
      html += '<div style="font-size:13px;font-weight:600;color:var(--danger);margin-bottom:6px;">🔴 紧急补货</div>';
      llmResult.urgent_items.forEach(function(item) {
        html += '<div class="alert-item"><div class="alert-icon danger"><i class="fas fa-exclamation"></i></div><div class="alert-text"><div class="title">' + item.name + '</div><div class="desc">建议进货 ' + (item.suggested_qty || '?') + ' 件 · ' + (item.reason || '') + '</div></div></div>';
      });
    }

    if (llmResult.plan_items && llmResult.plan_items.length > 0) {
      html += '<div style="font-size:13px;font-weight:600;color:var(--warning);margin-bottom:6px;margin-top:12px;">🟡 本周计划</div>';
      llmResult.plan_items.forEach(function(item) {
        html += '<div class="alert-item"><div class="alert-icon warning"><i class="fas fa-clock"></i></div><div class="alert-text"><div class="title">' + item.name + '</div><div class="desc">建议进货 ' + (item.suggested_qty || '?') + ' 件 · ' + (item.reason || '') + '</div></div></div>';
      });
    }
  } else {
    // 规则引擎降级
    html += '<div style="font-size:13px;color:var(--text-muted);margin-bottom:12px;">⚠️ LLM不可用，以下为RAG数据驱动分析</div>';

    // 紧急补货
    if (lowStock.length > 0) {
      html += '<div style="font-size:13px;font-weight:600;color:var(--danger);margin-bottom:6px;">🔴 低库存预警（RAG：这些品类顾客常买）</div>';
      lowStock.slice(0, 5).forEach(function(item) {
        html += '<div class="alert-item"><div class="alert-icon danger"><i class="fas fa-exclamation"></i></div><div class="alert-text"><div class="title">' + item.name + '（仅剩 ' + item.stock + ' 件）</div><div class="desc">品类热度：' + getCategoryHeat(item, categoryPreference) + ' · 建议尽快补货</div></div></div>';
      });
    }

    // 热销品补货建议
    if (hotItems.length > 0) {
      html += '<div style="font-size:13px;font-weight:600;color:var(--info);margin-bottom:6px;margin-top:12px;">📊 热销品补货建议（RAG：基于顾客偏好）</div>';
      html += '<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">顾客偏好：' + JSON.stringify(categoryPreference) + '</div>';
      hotItems.slice(0, 5).forEach(function(item, i) {
        html += '<div class="alert-item"><div class="alert-icon info"><i class="fas fa-fire"></i></div><div class="alert-text"><div class="title">#' + (i+1) + ' ' + item.name + '（售出 ' + item.qty + ' 件）</div><div class="desc">营收 ¥' + item.amount.toFixed(0) + ' · 建议保持库存充足</div></div></div>';
      });
    }
  }

  html += '<div style="font-size:10px;color:var(--text-muted);margin-top:12px;border-top:1px solid var(--border-light);padding-top:8px;">'
    + '<i class="fas fa-database mr-1"></i>数据来源：库存快照(' + lowStock.length + '条低库存) + 销售记录(' + salesLog.length + '单) + 顾客画像(' + Object.keys(custHistory).length + '人)'
    + ' → RAG检索 → ' + (llmResult ? 'DeepSeek分析' : '规则引擎') + '</div>';

  content.innerHTML = html;
  panel.scrollIntoView({ behavior: 'smooth' });
}

function getCategoryHeat(item, categoryPreference) {
  var name = item.name || '';
  if (name.includes('猫')) return categoryPreference['猫用'] ? '🔥 高（猫用品热销）' : '一般';
  if (name.includes('犬')) return categoryPreference['狗用'] ? '🔥 高（狗用品热销）' : '一般';
  if (name.includes('零食') || name.includes('罐头')) return categoryPreference['零食'] ? '🔥 高（零食热销）' : '一般';
  return '正常';
}

// ====== AI 内容 ======
async function generateAIContent() {
  $('wechatCopyPreview').textContent = '生成中...';
  $('communityCopyPreview').textContent = '生成中...';
  $('contentMaterial').innerHTML = '生成中...';

  try {
    var resp = await fetch('/api/content/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel: 'wechat' }),
    });
    var data = await resp.json();
    if (data.success && data.data) {
      $('wechatCopyPreview').textContent = data.data.wechat_copy || data.data.wechat || '（生成失败）';
      $('communityCopyPreview').textContent = data.data.community_copy || data.data.community || '（生成失败）';
      if (data.data.materials) {
        $('contentMaterial').innerHTML = data.data.materials.map(function(m){
          return '📸 ' + (typeof m === 'string' ? m : m.desc || m);
        }).join('<br>');
      }
    } else {
      // 降级：使用预置模板
      $('wechatCopyPreview').textContent = '夏天到啦☀️ 毛孩子做好驱虫了吗？即日起进店选购驱虫药享会员9折，满199送宠物凉垫一个！🏖️';
      $('communityCopyPreview').textContent = '邻居们好～最近天热，遛狗请选早晚凉快时段，备足饮水💧 有问题随时群里找我！';
      $('contentMaterial').innerHTML = '📸 洗护前后对比照3组<br>📸 新到爱肯拿猫粮实拍<br>📸 豆豆2岁生日派对照片';
    }
  } catch(e) {
    // 网络错误降级到模板
    $('wechatCopyPreview').textContent = '夏天到啦☀️ 毛孩子做好驱虫了吗？即日起进店选购驱虫药享会员9折，满199送宠物凉垫一个！🏖️';
    $('communityCopyPreview').textContent = '邻居们好～最近天热，遛狗请选早晚凉快时段，备足饮水💧 有问题随时群里找我！';
    $('contentMaterial').innerHTML = '📸 洗护前后对比照3组<br>📸 新到爱肯拿猫粮实拍<br>📸 豆豆2岁生日派对照片';
  }
}

async function copyContent(type) {
  var text = '';
  if (type === 'wechat') {
    text = $('wechatCopyPreview').textContent;
  } else if (type === 'community') {
    text = $('communityCopyPreview').textContent;
  }
  if (text && text !== '生成中...') {
    try {
      await navigator.clipboard.writeText(text);
      showToast2('已复制到剪贴板', 'success');
    } catch(e) {
      // fallback for older browsers
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      showToast2('已复制到剪贴板', 'success');
    }
  } else {
    showToast2('请先生成文案', 'warn');
  }
}

// ====== 时间筛选 ======
// 以前的 p 是个死参数——按钮高亮会变、数据纹丝不动，永远只显示"今日"。
// 现在它决定后端查询窗口，并且要落进全局，刷新/切图表时不能丢。
function switchPeriod(p, btn) {
  if (currentPeriod === p) { if (btn) btn.classList.add('active'); return; }
  currentPeriod = p;
  document.querySelectorAll('.time-filter .filter-btn').forEach(function(b){ b.classList.remove('active'); });
  if (btn) btn.classList.add('active');
  refreshDashboard();
}

// ====== 图表切换：营收 / 订单量 ======
function switchChart(type, btn) {
  chartMode = type;
  var r = document.getElementById('chartBtnRevenue');
  var o = document.getElementById('chartBtnOrders');
  if (r) r.classList.remove('active');
  if (o) o.classList.remove('active');
  if (btn) btn.classList.add('active');
  drawTrendChart();
}

// 把 trendData 里当前选中的那条线画到图上
function drawTrendChart() {
  if (!trendChartInst) return;
  var isRev = chartMode === 'revenue';
  var line = trendChartInst.data.datasets[0];
  trendChartInst.data.labels = trendData.labels;
  line.data = isRev ? trendData.revenue : trendData.orders;
  line.label = isRev ? '营收 (¥)' : '订单量';
  line.borderColor = isRev ? '#f9973e' : '#6366f1';
  line.backgroundColor = isRev ? 'rgba(249,151,62,0.1)' : 'rgba(99,102,241,0.1)';
  trendChartInst.update();
}

// ====== 近 12 个月经营明细表 ======
// 后端按月铺满 12 个桶再填数，所以哪怕某个月一单没有也会显示 0，不会缺行。
async function renderMonthlyTable() {
  var panel = $('monthlyPanel');
  var body = $('monthlyTableBody');
  if (!panel || !body) return;

  if (currentPeriod !== 'year') { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  body.innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:var(--text-muted);">加载中...</td></tr>';

  var rows = null;
  try {
    var r = await fetch(DASH_API_BASE + '/dashboard/monthly?months=12');
    var d = await r.json();
    if (d && d.success) rows = d.data || [];
  } catch(e) {}

  if (!rows || rows.length === 0) {
    body.innerHTML = '<tr><td colspan="6" style="padding:20px;text-align:center;color:var(--text-muted);">月度数据不可用</td></tr>';
    text('monthlyRange', '--');
    return;
  }

  text('monthlyRange', rows[0].label + ' ~ ' + rows[rows.length-1].label);

  var maxRev = Math.max.apply(null, rows.map(function(x){ return x.revenue || 0; })) || 1;
  body.innerHTML = rows.map(function(m, i) {
    var mom = '';
    if (m.partial) {
      // 当月还没走完，跟上个整月比是假比较，直接标明
      mom = '<span style="color:var(--text-muted);font-size:12px;">本月进行中</span>';
    } else if (m.mom === null || m.mom === undefined) {
      mom = '<span style="color:var(--text-muted);">--</span>';
    } else {
      var up = m.mom >= 0;
      mom = '<span style="color:' + (up ? 'var(--success)' : 'var(--danger)') + ';font-weight:600;">'
          + (up ? '▲' : '▼') + ' ' + Math.abs(m.mom).toFixed(1) + '%</span>';
    }
    var bar = '<div style="height:4px;background:var(--bg-input);border-radius:2px;margin-top:4px;">'
            + '<div style="height:100%;width:' + Math.round((m.revenue/maxRev)*100) + '%;background:var(--accent);border-radius:2px;"></div></div>';
    return '<tr style="border-top:1px solid var(--border-light);text-align:right;">'
      + '<td style="text-align:left;padding:10px 16px;font-weight:600;">' + m.label + '</td>'
      + '<td style="padding:10px 8px;">¥' + (m.revenue||0).toLocaleString() + bar + '</td>'
      + '<td style="padding:10px 8px;">' + m.orders + '</td>'
      + '<td style="padding:10px 8px;color:var(--text-secondary);">¥' + (m.avg_order||0).toLocaleString() + '</td>'
      + '<td style="padding:10px 8px;color:var(--text-secondary);">¥' + (m.profit||0).toLocaleString() + '</td>'
      + '<td style="padding:10px 16px;">' + mom + '</td>'
      + '</tr>';
  }).join('');
}
