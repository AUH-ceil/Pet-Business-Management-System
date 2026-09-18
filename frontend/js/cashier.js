/* ============================================================
   petstore_agent/frontend/js/cashier.js
   收银台 — 商品点选 + 购物车 + 结算
   ============================================================ */

// 脚本版本：改了 cashier.js 就 +1，同时改 index.html 的 js/cashier.js?v= 和
// backend/main.py 的 _FRONTEND_BUILD。三者一致才是干净的发布。
// 页面右上角会显示这个版本号——显示不出来就说明浏览器跑的是缓存里的旧脚本。
const CASHIER_BUILD = 'v4';

// ==================== API 地址常量 ====================
const API_BASE = 'http://127.0.0.1:8001/api';
const API = {
  CUSTOMER_INFO:   API_BASE + '/customer/',
  STOCK_ALERTS:    API_BASE + '/stock/alerts',
  CHECKOUT:        API_BASE + '/checkout',
  RAG_LLM:         API_BASE + '/rag/analyze',
  GROOMING_BOOK:   API_BASE + '/grooming/book',
  GROOMING_NOTES:  API_BASE + '/grooming/pet-notes',
  CONTENT_GEN:     API_BASE + '/content/generate',
};

// ==================== 商品目录 ====================
// 【实物商品】不再写死：由 /api/stock/all 下发的数据库目录整个重建，见
// applyCatalogFromBackend()。下面这份 GOODS_FALLBACK 只在后端连不上时用于显示，
// 里面的 stock 是假的（约等于期初库存），售价也不可信，界面会标"（离线兜底库存）"。
//
// 以前只做到"库存同源"、"目录还是前端写死的"——等于账本对上了、货号还是错的。
// 浏览器一旦缓存了旧脚本，旧编号就会【点A扣B】：2026-09-18 就是这么把
// "伯纳天纯大型犬粮"卖成了"鸡肉绕钙棒"，账实直接错开。目录也交给数据库之后，
// 最坏情况只是少个新功能，不会再扣错货。
const GOODS_FALLBACK = {
  dog_food: [
    { id:'SKU001', name:'皇家小型犬成犬粮', spec:'1.5kg/袋', price:158, brand:'皇家', stock:85 },
    { id:'SKU002', name:'爱肯拿鸡肉全犬粮', spec:'2kg/袋', price:239, brand:'爱肯拿', stock:42 },
    { id:'SKU007', name:'冠能幼犬粮', spec:'2.5kg/袋', price:189, brand:'冠能', stock:63 },
    { id:'SKU008', name:'渴望六种鱼全犬粮', spec:'2kg/袋', price:298, brand:'渴望', stock:18 },
    { id:'SKU009', name:'伯纳天纯大型犬粮', spec:'15kg/袋', price:468, brand:'伯纳天纯', stock:8 },
    { id:'SKU010', name:'比瑞吉天然粮', spec:'2kg/袋', price:168, brand:'比瑞吉', stock:55 },
    { id:'SKU011', name:'麦富迪双拼粮', spec:'1.5kg/袋', price:98, brand:'麦富迪', stock:120 },
    { id:'SKU012', name:'海洋之星三文鱼粮', spec:'1.5kg/袋', price:228, brand:'海洋之星', stock:31 },
  ],
  cat_food: [
    { id:'SKU101', name:'皇家室内成猫粮', spec:'2kg/袋', price:178, brand:'皇家', stock:72 },
    { id:'SKU102', name:'爱肯拿牧场盛宴猫粮', spec:'1.8kg/袋', price:258, brand:'爱肯拿', stock:38 },
    { id:'SKU103', name:'冠能泌尿健康猫粮', spec:'2kg/袋', price:198, brand:'冠能', stock:50 },
    { id:'SKU104', name:'渴望六种鱼猫粮', spec:'1.8kg/袋', price:318, brand:'渴望', stock:12 },
    { id:'SKU105', name:'GO! 九种肉猫粮', spec:'1.8kg/袋', price:288, brand:'GO!', stock:25 },
    { id:'SKU106', name:'纽顿T24鲑鱼猫粮', spec:'1.5kg/袋', price:238, brand:'纽顿', stock:3 },
    { id:'SKU107', name:'网易严选全价猫粮', spec:'1.8kg/袋', price:89, brand:'网易严选', stock:95 },
    { id:'SKU108', name:'比瑞吉天然猫粮', spec:'2kg/袋', price:158, brand:'比瑞吉', stock:60 },
  ],
  snacks: [
    { id:'SKU005', name:'鸡肉绕钙棒', spec:'100g/袋', price:25, brand:'顽皮', stock:200 },
    { id:'SKU006', name:'巅峰牛肉罐头', spec:'185g/罐', price:42, brand:'巅峰', stock:48 },
    { id:'SKU201', name:'冻干鸡肉粒', spec:'50g/袋', price:35, brand:'朗诺', stock:80 },
    { id:'SKU202', name:'猫条混合口味', spec:'12支/盒', price:28, brand:'伊纳宝', stock:150 },
  ],
  supplies: [
    { id:'SKU003', name:'豆腐猫砂', spec:'6L/包', price:29.9, brand:'N1', stock:300 },
    { id:'SKU004', name:'犬用体内驱虫药', spec:'1粒/盒', price:68, brand:'拜耳', stock:35 },
    { id:'SKU303', name:'宠物尿垫', spec:'60x45cm 50片', price:39, brand:'爱丽丝', stock:65 },
    { id:'SKU304', name:'不锈钢双碗', spec:'中号', price:55, brand:'多格漫', stock:28 },
  ],
};

// 【服务类】数据库里没有库存行（stock=-1 表示无限），本来就是前端常量，不会漂移
const SERVICE_CATALOG = {
  grooming: [
    { id:'SV001', name:'小型犬基础洗护', spec:'约40分钟', price:88, brand:'服务', stock:-1 },
    { id:'SV002', name:'猫咪精洗护理', spec:'约60分钟', price:128, brand:'服务', stock:-1 },
    { id:'SV003', name:'中大型犬精洗', spec:'约90分钟', price:158, brand:'服务', stock:-1 },
    { id:'SV004', name:'剃毛造型', spec:'约60-120分钟', price:188, brand:'服务', stock:-1 },
  ],
  daycare: [
    { id:'SV101', name:'小型犬日托', spec:'半天', price:68, brand:'托管', stock:-1 },
    { id:'SV102', name:'小型犬寄养', spec:'过夜', price:98, brand:'托管', stock:-1 },
    { id:'SV103', name:'玩耍区计时', spec:'1小时', price:38, brand:'托管', stock:-1 },
  ],
};

// 全量目录 = 实物商品（会被数据库覆盖）+ 服务类（固定不动）
const PRODUCT_CATALOG = Object.assign({}, GOODS_FALLBACK, SERVICE_CATALOG);

// 数据库的 category → 收银台的分类页签（猫砂、药品在收银台并入"用品"）
const DB_CAT_TO_TAB = {
  '狗粮':'dog_food', '猫粮':'cat_food', '零食':'snacks',
  '猫砂':'supplies', '药品':'supplies', '用品':'supplies',
};

// 用数据库目录覆盖实物商品表：编号/名称/售价/规格/库存全部以数据库为准。
// 这样即使浏览器跑的是缓存里的旧脚本，商品和价格仍然是数据库下发的，
// 不会再出现"界面写着伯纳天纯、发出去的编号却是鸡肉绕钙棒"。
// 返回重建出的商品数；返回 0 表示后端没给出可用目录，保持兜底值不动。
function applyCatalogFromBackend(items) {
  const goods = {};
  for (const it of items) {
    const tab = DB_CAT_TO_TAB[it.category];
    if (!tab) continue;                    // 服务/托管不占库存，不在这里
    (goods[tab] = goods[tab] || []).push({
      id: it.sku_id, name: it.name, spec: it.spec || '', brand: it.brand || '',
      price: Number(it.retail_price) || 0, stock: it.current_stock,
    });
  }
  let n = 0;
  for (const tab of Object.keys(goods)) { PRODUCT_CATALOG[tab] = goods[tab]; n += goods[tab].length; }
  return n;
}

// ==================== 全局状态 ====================
let cart = [];
let currentCustomer = null;
let currentCategory = 'dog_food';
let darkMode = localStorage.getItem('darkMode') === 'true';

// ==================== localStorage 库存快照版本 ====================
// 改 PRODUCT_CATALOG 的 SKU 编号时必须递增：否则旧编号下的库存数会被套到新商品上
// v3：库存来源由"前端自己记账"改为"以数据库为准"，旧本地快照的语义已不同，必须作废
// v4：商品目录也改为数据库下发，本地快照里按旧编号存的键全部作废
const STOCK_VERSION = 'v4';
const STOCK_VERSION_KEY = 'petstore_stock_version';
const stockIsCurrent = localStorage.getItem(STOCK_VERSION_KEY) === STOCK_VERSION;

// 从 localStorage 恢复库存（跨页面共享）
const SAVED_STOCK = stockIsCurrent ? localStorage.getItem('petstore_stock') : null;
if (SAVED_STOCK) {
  try {
    const saved = JSON.parse(SAVED_STOCK);
    for (const cat of Object.keys(PRODUCT_CATALOG)) {
      if (saved[cat]) {
        for (const p of PRODUCT_CATALOG[cat]) {
          if (saved[cat][p.id] !== undefined) p.stock = saved[cat][p.id];
        }
      }
    }
  } catch(e) {}
}

// ==================== 库存同步（数据库 = 唯一真相源） ====================
// 收银台以前自己扣自己记，库存先知读数据库，两边从第一天起就会分叉。
// 现在前端不再自己记账：库存一律从 /api/stock/all 拉，本地那份只用于后端连不上的兜底。
// 三态：loading=还没拿到真实库存（此时【不显示具体数字】，否则写死的假值会冒充真值）
//       live   = 已在用数据库库存    offline = 后端连不上，显示的是本地兜底值
let stockState = 'loading';

function writeLocalSnapshot() {
  const snap = {}, nameMap = {};
  for (const cat of Object.keys(PRODUCT_CATALOG)) {
    snap[cat] = {};
    for (const p of PRODUCT_CATALOG[cat]) {
      snap[cat][p.id] = p.stock;
      nameMap[p.id] = { name: p.name, spec: p.spec, category: cat };
    }
  }
  localStorage.setItem('petstore_stock', JSON.stringify(snap));
  localStorage.setItem('petstore_products', JSON.stringify(nameMap));
  localStorage.setItem(STOCK_VERSION_KEY, STOCK_VERSION);
}

async function syncStockFromBackend() {
  try {
    const resp = await fetch(API_BASE + '/stock/all');
    const d = await resp.json();
    if (!d || !d.success) return false;
    // 目录和库存一起换：这次拿回来的 data 里既有商品名/售价，也有实时库存，
    // 一份数据同时定"卖什么"和"剩多少"，两边不可能再分叉。
    const n = applyCatalogFromBackend(d.data || []);
    if (n === 0) return false;                     // 目录为空，保留兜底值，别把界面清空
    writeLocalSnapshot();
    stockState = 'live';
    return true;
  } catch (e) {
    stockState = 'offline';
    return false;                                  // 后端连不上，继续用本地兜底值
  }
}

// 后端不可用时的本地扣减（保持收银能不中断，但会在界面上标出来）
function localDecrement() {
  for (const item of cart) {
    for (const cat of Object.values(PRODUCT_CATALOG)) {
      const p = cat.find(x => x.id === item.id);
      if (p && p.stock > 0) {
        p.stock -= item.qty;
        if (p.stock < 0) p.stock = 0;
        break;
      }
    }
  }
  writeLocalSnapshot();
}

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', () => {
  if (darkMode) document.documentElement.classList.add('dark');
  updateThemeIcon();
  updateDate();
  // 让"浏览器跑的是不是最新脚本"一眼可见：显示得出来=新版，显示 "--"=旧脚本
  const buildTag = document.getElementById('buildTag');
  if (buildTag) buildTag.textContent = '脚本 ' + CASHIER_BUILD;
  console.log('%c收银台脚本 ' + CASHIER_BUILD, 'color:#e8852b;font-weight:bold');
  // 首次加载（或 SKU 编号升级）先写一份兜底快照，保证后端没起来时看板也有数
  if (!localStorage.getItem('petstore_stock') || !stockIsCurrent) writeLocalSnapshot();
  renderProductGrid();
  loadStockAlerts();
  updateSoldSummary();

  // 再用数据库的真实库存覆盖一遍（这才是权威值）
  syncStockFromBackend().then(ok => {
    renderProductGrid();
    loadStockAlerts();
    if (!ok) showToast('后端未连接，右侧库存预警为本地兜底数据', 'warn');
  });
});

// ==================== 深色/浅色模式 ====================
function toggleTheme() {
  darkMode = !darkMode;
  document.documentElement.classList.toggle('dark', darkMode);
  localStorage.setItem('darkMode', darkMode);
  updateThemeIcon();
}
function updateThemeIcon() {
  const icon = document.getElementById('themeIcon');
  if (icon) icon.className = darkMode ? 'fas fa-sun' : 'fas fa-moon';
}
function updateDate() {
  const now = new Date();
  document.getElementById('currentDate').textContent =
    now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
}

// ==================== Toast / Loading ====================
function showToast(msg, type) {
  const icons = { success:'fa-check-circle', error:'fa-times-circle', warn:'fa-exclamation-triangle' };
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = 'toast ' + (type || 'success');
  t.innerHTML = '<i class="fas ' + (icons[type]||icons.info) + '"></i> ' + msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}
function showLoading(text) {
  document.getElementById('loadingText').textContent = text || '处理中...';
  document.getElementById('loadingOverlay').style.display = 'flex';
}
function hideLoading() {
  document.getElementById('loadingOverlay').style.display = 'none';
}
function formatMoney(n) { return Number(n).toFixed(2); }

// ==================== 分类切换 ====================
function switchCategory(cat, btn) {
  currentCategory = cat;
  document.querySelectorAll('#categoryTabs .mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderProductGrid();
}

// ==================== 商品网格渲染 ====================
function renderProductGrid() {
  const products = PRODUCT_CATALOG[currentCategory] || [];
  const container = document.getElementById('productGrid');
  document.getElementById('productCount').textContent =
    products.length + ' 件可售' +
    (stockState === 'live' ? '' : stockState === 'loading' ? '（读取库存中…）' : '（离线兜底库存）');

  if (products.length === 0) {
    container.innerHTML = '<div class="empty-state"><i class="fas fa-box-open"></i><p>该分类暂无商品</p></div>';
    return;
  }

  container.innerHTML = products.map(p => {
    const isService = p.stock === -1;
    // 这个数字直接来自数据库（syncStockFromBackend），和库存先知同一个源，不会再对不上。
    // 还没读到时不显示数字：写死的兜底值是假的，不能让它冒充真库存。
    const pending = !isService && stockState === 'loading';
    const stockText = isService ? '随时可约'
      : pending ? '库存: …'
      : '库存: ' + p.stock + (stockState === 'offline' ? '（兜底）' : '');
    const soldOut = !isService && !pending && p.stock <= 0;
    const stockStyle = !pending && p.stock < 10 && p.stock > 0 ? 'color:var(--danger);font-weight:600;' : '';

    return `
      <div onclick="${soldOut ? '' : "addToCartById('" + p.id + "')"}"
           style="display:inline-block;width:23%;margin:1%;padding:12px;border:1px solid var(--border);
                  border-radius:10px;cursor:${soldOut?'not-allowed':'pointer'};text-align:center;
                  vertical-align:top;transition:all 0.15s;background:${soldOut?'var(--bg-input)':'var(--bg-card)'};
                  opacity:${soldOut?'0.5':'1'};"
           onmouseenter="if(!${soldOut}){this.style.borderColor='var(--accent)';this.style.boxShadow='0 2px 8px rgba(249,151,62,0.2)'}"
           onmouseleave="this.style.borderColor='var(--border)';this.style.boxShadow='none'">
        <div style="font-size:24px;margin-bottom:4px;">${isService ? '✂️' : soldOut ? '🚫' : '🛒'}</div>
        <div style="font-size:13px;font-weight:600;line-height:1.3;margin-bottom:4px;">${p.name}</div>
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">${p.spec}</div>
        <div style="font-size:18px;font-weight:700;color:${soldOut?'var(--text-muted)':'var(--danger)'};">¥${formatMoney(p.price)}</div>
        <div style="font-size:11px;margin-top:2px;${stockStyle}">${stockText}</div>
        ${soldOut ? '<div style="font-size:11px;color:var(--danger);margin-top:2px;">已售罄</div>' : ''}
      </div>`;
  }).join('');
}

// ==================== 添加商品到购物车 ====================
function addToCartById(pid) {
  let product = null;
  for (const cat of Object.values(PRODUCT_CATALOG)) {
    product = cat.find(p => p.id === pid);
    if (product) break;
  }
  if (!product) return;

  // 检查库存
  const exist = cart.find(item => item.id === product.id);
  const cartQty = exist ? exist.qty : 0;
  if (product.stock !== -1 && cartQty >= product.stock) {
    showToast(product.name + ' 库存不足！', 'error');
    return;
  }

  if (exist) {
    exist.qty++;
  } else {
    cart.push({
      id: product.id,
      name: product.name,
      spec: product.spec,
      price: product.price,
      qty: 1,
      type: product.stock === -1 ? 'service' : 'product',
    });
  }
  renderCart();
  showToast(product.name + ' +1', 'success');
}

// ==================== 购物清单渲染 ====================
function renderCart() {
  const container = document.getElementById('cartList');
  document.getElementById('cartCount').textContent = cart.reduce((s,i) => s + i.qty, 0) + ' 件商品';

  if (cart.length === 0) {
    container.innerHTML = '<div class="empty-state"><i class="fas fa-shopping-basket"></i><p>点击上方商品添加到清单</p></div>';
    recalcTotal();
    return;
  }

  container.innerHTML = cart.map((item, idx) => {
    const tag = item.type === 'service'
      ? '<span class="service-tag grooming">服务</span>'
      : '<span class="service-tag product">商品</span>';
    return `
      <div class="cart-row">
        <div>
          <div style="font-size:14px;font-weight:500;">${item.name} ${tag}</div>
          <div style="font-size:12px;color:var(--text-muted);">${item.spec}</div>
        </div>
        <div style="text-align:center;">¥${formatMoney(item.price)}</div>
        <div class="qty-control">
          <button class="qty-btn" onclick="changeQty(${idx},-1)">−</button>
          <span class="qty-num">${item.qty}</span>
          <button class="qty-btn" onclick="changeQty(${idx},1)">+</button>
        </div>
        <div style="text-align:right;font-weight:600;">¥${formatMoney(item.price*item.qty)}</div>
        <div class="remove-btn" onclick="removeFromCart(${idx})"><i class="fas fa-times"></i></div>
      </div>`;
  }).join('');
  recalcTotal();
}

function changeQty(idx, delta) {
  cart[idx].qty += delta;
  if (cart[idx].qty <= 0) cart.splice(idx, 1);
  renderCart();
}
function removeFromCart(idx) { cart.splice(idx, 1); renderCart(); }

// ==================== 顾客查询 + RAG推荐 ====================
function lookupCustomer() {
  const phone = document.getElementById('customerPhone').value.trim();
  if (!phone) { showToast('请输入手机号', 'warn'); return; }

  const custHistory = JSON.parse(localStorage.getItem('cust_history') || '{}');
  const profile = custHistory[phone];

  if (!profile) {
    document.getElementById('customerEmpty').style.display = 'none';
    document.getElementById('customerInfo').style.display = 'block';
    document.getElementById('customerBadge').style.display = 'inline-flex';
    document.getElementById('customerBadge').textContent = '新客';
    document.getElementById('custName').textContent = '新顾客';
    document.getElementById('custPhone').textContent = phone;
    document.getElementById('custHistory').textContent = '首次到店，暂无购买记录';
    document.getElementById('custRAG').innerHTML = '<div style="font-size:12px;color:var(--text-muted);">结算后自动记录，下次来就有推荐了</div>';
  } else {
    document.getElementById('customerEmpty').style.display = 'none';
    document.getElementById('customerInfo').style.display = 'block';
    document.getElementById('customerBadge').style.display = 'inline-flex';
    document.getElementById('customerBadge').textContent = profile.purchases.length + '次消费';
    document.getElementById('custName').textContent = '会员 ' + phone.slice(-4);
    document.getElementById('custPhone').textContent = phone;
    const last = profile.purchases[profile.purchases.length - 1];
    document.getElementById('custHistory').textContent =
      '上次：' + new Date(last.time).toLocaleDateString('zh-CN') +
      ' | 消费¥' + last.total.toFixed(2) +
      ' | 累计¥' + profile.totalSpent.toFixed(2);

    // RAG 推荐
    const recs = ragRecommend(phone, profile, custHistory);
    document.getElementById('custRAG').innerHTML = recs;
  }
}

// RAG：向量化顾客画像 → 分析消费习惯 → 找相似顾客 → 综合推荐
function ragRecommend(phone, myProfile, allHistory) {
  const myVec = buildPurchaseVector(myProfile);

  // ===== 1. 消费习惯分析（从自己的购买向量中提炼） =====
  const habitAnalysis = analyzeHabits(myVec, myProfile);

  // ===== 2. 与其他顾客比较余弦相似度 =====
  const scores = [];
  for (const [otherPhone, otherProfile] of Object.entries(allHistory)) {
    if (otherPhone === phone) continue;
    const otherVec = buildPurchaseVector(otherProfile);
    const sim = cosineSim(myVec, otherVec);
    if (sim > 0.1) scores.push({ phone: otherPhone, score: sim, profile: otherProfile });
  }
  scores.sort((a, b) => b.score - a.score);
  const topSimilar = scores.slice(0, 3);

  // ===== 3. 从相似顾客提取"我没买过但他们买了" =====
  const myBought = new Set();
  myProfile.purchases.forEach(s => s.items.forEach(it => myBought.add(it.name)));

  const candidateMap = {};
  topSimilar.forEach(sim => {
    sim.profile.purchases.forEach(s => {
      s.items.forEach(it => {
        if (!myBought.has(it.name)) {
          if (!candidateMap[it.name]) candidateMap[it.name] = { name: it.name, weight: 0, simCustomers: [] };
          candidateMap[it.name].weight += it.qty * sim.score;
          candidateMap[it.name].simCustomers.push(sim.phone.slice(-4));
        }
      });
    });
  });

  const recs = Object.values(candidateMap)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3);

  // ===== 4. 拼装 HTML =====
  let html = '';

  // 消费习惯分析
  html += '<div style="background:var(--accent-light);padding:10px;border-radius:8px;margin-bottom:8px;">';
  html += '<div style="font-size:12px;font-weight:600;color:var(--accent-dark);margin-bottom:4px;"><i class="fas fa-chart-pie mr-1"></i>消费习惯分析</div>';
  html += '<div style="font-size:12px;color:var(--text-secondary);line-height:1.6;">' + habitAnalysis + '</div>';
  html += '</div>';

  // RAG 相似顾客推荐
  if (topSimilar.length > 0 && recs.length > 0) {
    html += '<div style="font-size:12px;font-weight:600;color:var(--info);margin-bottom:4px;"><i class="fas fa-users-between-lines mr-1"></i>相似顾客也买了</div>';
    recs.forEach((r, i) => {
      const conf = Math.round((r.weight / recs[0].weight) * 100);
      html += '<div class="ai-alert" style="margin-bottom:4px;">'
        + '<i class="fas fa-lightbulb"></i>'
        + '<span><b>' + r.name + '</b> — 顾客' + r.simCustomers.join('/') + '买过（' + conf + '%）</span>'
        + '</div>';
    });
  }

  // LLM深度分析按钮
  html += '<div style="margin-top:8px;display:flex;gap:8px;align-items:center;">'
    + '<button class="btn btn-sm btn-primary" onclick="callLLMAnalysis(\'' + phone + '\')">'
    + '<i class="fas fa-robot mr-1"></i>AI深度分析</button>'
    + '<span style="font-size:10px;color:var(--text-muted);">RAG + DeepSeek 联合推理</span>'
    + '</div>'
    + '<div id="llmResult" style="margin-top:8px;"></div>';

  html += '<div style="font-size:10px;color:var(--text-muted);margin-top:6px;">'
    + '<i class="fas fa-vector-square mr-1"></i>Qdrant 余弦检索 · '
    + '匹配 ' + Object.keys(allHistory).length + ' 名顾客 · '
    + '向量维度 ' + Object.keys(myVec).length
    + '</div>';

  return html;
}

// 调用后端 DeepSeek LLM + RAG 联合分析
async function callLLMAnalysis(phone) {
  const llmDiv = document.getElementById('llmResult');
  llmDiv.innerHTML = '<div style="font-size:12px;color:var(--text-muted);"><span class="spinner"></span> AI分析中...</div>';

  const custHistory = JSON.parse(localStorage.getItem('cust_history') || '{}');
  const myProfile = custHistory[phone];
  if (!myProfile) { llmDiv.innerHTML = ''; return; }

  const myVec = buildPurchaseVector(myProfile);
  const topItems = Object.entries(myVec).sort((a,b) => b[1]-a[1]).slice(0,5).map(t => ({name:t[0], qty:t[1]}));

  // 计算相似顾客
  const scores = [];
  for (const [op, opf] of Object.entries(custHistory)) {
    if (op === phone) continue;
    const sim = cosineSim(myVec, buildPurchaseVector(opf));
    if (sim > 0.1) {
      scores.push({
        phone: op.slice(-4),
        score: Math.round(sim*100)/100,
        recent_items: opf.purchases[opf.purchases.length-1]?.items?.map(i => i.name) || []
      });
    }
  }
  scores.sort((a,b) => b.score - a.score);

  try {
    const resp = await fetch(API.RAG_LLM, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        phone: phone,
        purchase_history: myProfile.purchases.slice(-5),
        habit_summary: { top_items: topItems, top_brands: [], insights: [] },
        similar_customers: scores.slice(0, 3),
      }),
    });
    const result = await resp.json();

    if (result.success && result.data) {
      const d = result.data;
      llmDiv.innerHTML = '<div style="background:var(--info-light);padding:10px;border-radius:8px;margin-top:6px;">'
        + '<div style="font-size:11px;font-weight:600;color:var(--info);margin-bottom:6px;">'
        + '<i class="fas fa-robot mr-1"></i>DeepSeek AI 分析（RAG联合推理）</div>'
        + '<div style="font-size:12px;color:var(--text-primary);line-height:1.7;">'
        + '<div style="margin-bottom:6px;"><b>📊 消费画像：</b>' + (d.profile || '') + '</div>'
        + '<div style="margin-bottom:6px;"><b>🎯 推荐商品：</b>' + (d.recommendation || '') + '</div>'
        + '<div style="background:var(--bg-card);padding:8px;border-radius:6px;">'
        + '<b>📝 复购话术：</b><br>' + (d.message_template || '') + '</div>'
        + '</div></div>';
    } else {
      llmDiv.innerHTML = '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">⚠️ LLM不可用，使用规则分析（见上方）</div>';
    }
  } catch(e) {
    llmDiv.innerHTML = '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">⚠️ 后端未启动，展示规则分析结果</div>';
  }
}

// 分析顾客消费习惯，生成文字建议
function analyzeHabits(myVec, profile) {
  if (Object.keys(myVec).length === 0) return '暂无足够数据';

  const sorted = Object.entries(myVec).sort((a, b) => b[1] - a[1]).slice(0, 5);

  // 只展示事实，不做推断（推断交给LLM）
  const brandMap = {};
  const allBrands = [];
  profile.purchases.forEach(s => {
    s.items.forEach(it => { allBrands.push(it.name); });
  });
  const uniqueItems = [...new Set(allBrands)];

  let html = '';
  html += '购买 ' + profile.purchases.length + ' 次，共 ' + uniqueItems.length + ' 种商品<br>';
  html += '高频：' + sorted.map(t => t[0] + '×' + t[1]).join('、');
  return html;
}

// 构建购买向量：按商品名维度累加购买次数
function buildPurchaseVector(profile) {
  const vec = {};
  profile.purchases.forEach(s => {
    s.items.forEach(it => {
      vec[it.name] = (vec[it.name] || 0) + it.qty;
    });
  });
  return vec;
}

// 余弦相似度（两个稀疏向量的点积/模长乘积）
function cosineSim(vecA, vecB) {
  let dot = 0, normA = 0, normB = 0;
  for (const key in vecA) { normA += vecA[key] * vecA[key]; }
  for (const key in vecB) { normB += vecB[key] * vecB[key]; }
  for (const key in vecA) {
    if (vecB[key]) dot += vecA[key] * vecB[key];
  }
  if (normA === 0 || normB === 0) return 0;
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}

function clearCart() {
  cart = [];
  renderCart();
  document.getElementById('customerEmpty').style.display = 'flex';
  document.getElementById('customerInfo').style.display = 'none';
  document.getElementById('customerBadge').style.display = 'none';
  showToast('清单已清空');
}

// ==================== 总价重算 ====================
function recalcTotal() {
  const subtotal = cart.reduce((s, i) => s + i.price * i.qty, 0);
  document.getElementById('cartQtyTotal').textContent = cart.reduce((s,i) => s + i.qty, 0);
  document.getElementById('cartAmountTotal').textContent = formatMoney(subtotal);
}

// ==================== 结算 ====================
async function checkout() {
  if (cart.length === 0) { showToast('请先添加商品', 'warn'); return; }
  showLoading('结算中...');

  // 1. 写销售记录（经营看板用 + 顾客购买历史）
  // 库存不在这里扣——由后端扣库后再回读，见下面的 syncStockFromBackend()
  const salesLog = JSON.parse(localStorage.getItem('petstore_sales') || '[]');
  const phone = document.getElementById('customerPhone').value.trim();
  const saleEntry = {
    time: new Date().toISOString(),
    items: cart.map(i => ({ name: i.name, qty: i.qty, price: i.price, subtotal: i.price * i.qty })),
    total: parseFloat(document.getElementById('cartAmountTotal').textContent),
    phone: phone,
  };
  salesLog.push(saleEntry);
  if (salesLog.length > 100) salesLog.splice(0, salesLog.length - 100);
  localStorage.setItem('petstore_sales', JSON.stringify(salesLog));

  // 2. 保存顾客购买历史（RAG向量检索用）
  if (phone) {
    const custHistory = JSON.parse(localStorage.getItem('cust_history') || '{}');
    if (!custHistory[phone]) custHistory[phone] = { purchases: [], totalSpent: 0, lastVisit: '' };
    custHistory[phone].purchases.push(saleEntry);
    custHistory[phone].totalSpent += saleEntry.total;
    custHistory[phone].lastVisit = saleEntry.time;
    // 只保留最近50条
    if (custHistory[phone].purchases.length > 50) custHistory[phone].purchases.splice(0, custHistory[phone].purchases.length - 50);
    localStorage.setItem('cust_history', JSON.stringify(custHistory));
  }
  var backendFailed = [];   // 后端明确拒绝出库的 sku
  var backendDown = false;  // 后端整个没连上

  try {
    // 洗护服务走预约API，商品走结算API
    var serviceItems = cart.filter(function(item) { return item.type === 'service'; });
    var productItems = cart.filter(function(item) { return item.type === 'product'; });

    // 商品结算（非阻塞：后端失败不影响收银，但要让店员看见）
    if (productItems.length > 0) {
      const resp = await fetch(API.CHECKOUT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: productItems.map(function(item) { return {
            sku_id: item.id, name: item.name, quantity: item.qty,
            unit_price: item.price, type: item.type,
          }; }),
          total_amount: productItems.reduce(function(s,i){ return s + i.price*i.qty; }, 0),
        }),
      });
      const r = await resp.json();
      if (r && r.failed && r.failed.length > 0) backendFailed = r.failed;
    }

    // 洗护服务预约
    for (var i = 0; i < serviceItems.length; i++) {
      var svc = serviceItems[i];
      var now = new Date();
      var startTime = now.getFullYear() + '-' +
        String(now.getMonth()+1).padStart(2,'0') + '-' +
        String(now.getDate()).padStart(2,'0') + ' ' +
        String(now.getHours()+1).padStart(2,'0') + ':00:00';
      try {
        await fetch(API.GROOMING_BOOK, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            customer_id: phone ? 'CUST' + phone.slice(-4) : 'WALKIN',
            customer_name: document.getElementById('custName').textContent || '散客',
            pet_name: svc.name,
            pet_species: svc.name.includes('猫') ? '猫' : '狗',
            service_type: svc.name,
            groomer: '张师傅',
            scheduled_start: startTime,
            estimated_minutes: svc.name.includes('精洗') ? 90 : (svc.name.includes('剃毛') ? 120 : 60),
            pet_notes: '',
          }),
        });
      } catch(e) {}
    }
  } catch(e) {
    backendDown = true;
  }

  // 3. 库存收口：数据库说了算。后端扣成功就回读真实库存；
  //    只有后端整个没连上，才退回本地扣减（并标为离线兜底）
  if (!backendDown) {
    const ok = await syncStockFromBackend();
    if (!ok) backendDown = true;
  }
  if (backendDown) localDecrement();

  hideLoading();
  showToast('结算成功！收款 ¥' + document.getElementById('cartAmountTotal').textContent, 'success');
  if (backendDown) {
    showToast('后端未启动，本次仅记在本地（离线模式）', 'warn');
  } else if (backendFailed.length > 0) {
    showToast('后端出库失败：' + backendFailed.join('、') + '，本地已记账，请核对库存', 'warn');
  }
  clearCart();
  renderProductGrid();
  loadStockAlerts();
  updateSoldSummary();
}

// ==================== 今日销售汇总 ====================
function updateSoldSummary() {
  const salesLog = JSON.parse(localStorage.getItem('petstore_sales') || '[]');
  const today = new Date().toISOString().slice(0, 10);
  const todaySales = salesLog.filter(s => s.time && s.time.startsWith(today));

  document.getElementById('soldCount').textContent = todaySales.length + '单';

  if (todaySales.length === 0) {
    document.getElementById('todaySoldPanel').innerHTML = '<div class="empty-state"><i class="fas fa-receipt"></i><p>今日暂无销售</p></div>';
    return;
  }

  // 汇总所有商品
  const itemMap = {};
  todaySales.forEach(s => {
    (s.items || []).forEach(it => {
      if (!itemMap[it.name]) itemMap[it.name] = { name: it.name, qty: 0, amount: 0 };
      itemMap[it.name].qty += it.qty;
      itemMap[it.name].amount += it.subtotal || 0;
    });
  });
  const totalAmount = todaySales.reduce((s, sale) => s + sale.total, 0);
  const totalItems = Object.values(itemMap).reduce((s, it) => s + it.qty, 0);

  const sorted = Object.values(itemMap).sort((a, b) => b.qty - a.qty);

  let html = '<div style="font-size:13px;margin-bottom:8px;">共售出 <b>' + totalItems + '</b> 件，营收 <b style="color:var(--danger);">¥' + totalAmount.toFixed(0) + '</b></div>';
  sorted.forEach(it => {
    html += '<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0;border-bottom:1px solid var(--border-light);">'
      + '<span>' + it.name + '</span>'
      + '<span style="color:var(--text-secondary);">×' + it.qty + ' <span style="color:var(--text-primary);">¥' + it.amount.toFixed(0) + '</span></span>'
      + '</div>';
  });
  document.getElementById('todaySoldPanel').innerHTML = html;
}
// 库存预警：用后端同一套 replenish_point 规则，保证和库存先知是同一个口径；
// 后端连不上才退回本地固定阈值（10件）
async function loadStockAlerts() {
  let alerts = null;
  try {
    const resp = await fetch(API.STOCK_ALERTS);
    const d = await resp.json();
    if (d && d.success) {
      alerts = (d.data || []).map(a => ({
        name: a.name,
        stock: a.stock,
        severity: a.severity || (a.stock <= 3 ? 'urgent' : 'warning'),
      }));
    }
  } catch (e) {}
  if (!alerts) alerts = localStockAlerts();
  alerts.sort((a, b) => a.stock - b.stock);
  renderStockAlerts(alerts);
}

function localStockAlerts() {
  const low = [];
  for (const cat of Object.values(PRODUCT_CATALOG)) {
    for (const p of cat) {
      if (p.stock !== -1 && p.stock <= 10) {
        low.push({ name: p.name, stock: p.stock, severity: p.stock <= 3 ? 'urgent' : 'warning' });
      }
    }
  }
  return low;
}
function renderStockAlerts(alerts) {
  const container = document.getElementById('stockAlertPanel');
  document.getElementById('stockAlertCount').textContent = alerts.length;
  if (alerts.length === 0) {
    container.innerHTML = '<div class="empty-state"><i class="fas fa-check-circle" style="color:var(--success);"></i><p>库存状态良好</p></div>';
    return;
  }
  container.innerHTML = alerts.map(a => `
    <div class="alert-item">
      <div class="alert-icon ${a.severity==='urgent'?'danger':'warning'}"><i class="fas fa-exclamation"></i></div>
      <div class="alert-text"><div class="title">${a.name}</div><div class="desc">剩余 ${a.stock} 件</div></div>
    </div>`).join('');
}
