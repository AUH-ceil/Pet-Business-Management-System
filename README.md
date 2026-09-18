# 宠物店智慧经营中枢

一套宠物店的进销存 + 客户维系 + 服务管理系统。FastAPI 提供接口，MySQL 存业务数据，
前端是原生 HTML/JS —— **没有构建步骤**，改完刷新就生效。

后端把业务拆成 5 个 Agent（库存 / 客户 / 洗护 / 活体健康 / 内容），每个都是
「**规则引擎打底 + LLM 可选增强**」的结构：LLM 连不上时自动降级到规则，功能不中断，
只是建议没那么"聪明"。

> 这是一个面试 / 作品集项目。比起功能数量，它更想演示几件工程上的判断：
> 分层降级不阻断启动、时间口径的自然区间对齐、进销存的原子性与 FIFO 扣减、
> 以及**哪些没做**的诚实交代（见文末「已知边界」）。

---

## 快速开始

**环境要求**：**Python 3.10+**、MySQL 8.0（默认连 `localhost:3306`）

> ⚠️ **Python 3.10 是硬门槛，装依赖失败十有八九是它。**
> 门槛由 `langgraph` 决定（它要求 `>=3.10`），`pydantic 2` 要求 `>=3.8`。
> CentOS 7 / 阿里云 ECS 自带的 `python3` 是 **3.6.8**，在那个版本上 `pip` 只会
> 列到 `fastapi 0.83.0` —— **那不是网络问题**，是 pip 按本机 Python 版本过滤的结果。
> 往低改版本号没用，退到 0.83.0 之后 pydantic 和 langgraph 会接着失败。
> 先跑 `python3 --version` 确认，详见「部署到服务器」。

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 配置（.env 已被 .gitignore 挡住，不会进版本库）
cp .env.example .env
#    填上 DEEPSEEK_API_KEY 才能用 LLM；不填也能跑，会自动降级到规则引擎

# 3. 启动
python start.py
```

打开 **http://localhost:8001** （根路径会 302 跳到 `/app` 收银台）。

首次启动会自动建库建表并灌入种子数据：31 个商品、24 条库存快照、5 个会员，
以及 **2025-09-18 ~ 2026-09-17 整整一年**的经营数据（362 天日汇总 + 3636 条商品日销）。
灌数据是**幂等**的，重复启动不会翻倍。

API 文档在 http://localhost:8001/docs ，当前生效的降级层级在 http://localhost:8001/api/system/status 。

---

## 功能

| 页面 | 路由 | 干什么 |
|---|---|---|
| 收银台 | `/app` | 扫码/点选商品 → 购物车 → 结算，逐件 FIFO 出库并更新会员消费 |
| 经营看板 | `/dashboard` | 今日/本周/本月/近一年四个口径的营收、趋势、热销 TOP5，近一年带 12 个月明细表 |
| 库存先知 | `/inventory` | 库存清单、低库存/效期/滞销预警、AI 补货分析、**到货入库（多行进货单）** |
| 客户档案 | `/customers` | 会员画像、复购率、流失预警、AI 维系建议 |
| 洗护预约 | `/grooming` | 美容师排班、预约登记、宠物洗护备注 |
| 活体健康 | `/health` | 疫苗/驱虫/体检到期提醒 |
| 宠物托管 | `/daycare` | 寄养/日托签到签退、在托状态 |
| 内容运营 | `/content` | 一键生成朋友圈文案、社群公告、今日推荐素材 |

另外有两条 **LangGraph DAG**：每日开店（库存检查 → 效期扫描 → 排班 → 客户维系 → 内容生成）
和顾客到店（会员识别 → 消费出库 → 更新画像 → 生成服务报告），
通过 `/api/dag/daily` 和 `/api/dag/customer` 触发。

### 到货入库

进货走 `/inventory` 页的「到货入库」卡片：一次可录多行，每行一个商品。
**整张进货单是一个事务** —— 任何一行不合法（SKU 不存在、数量非正、进价负数、
效期格式不对）就全部退回，一条都不写，并报出是第几行。

设计上刻意这么选：现实里货要么到了要么没到，部分提交会让账和事实分叉，
事后谁也说不清哪半是真的。表单下方有「最近入库记录」，录完立刻能对账。

---

## 架构：三层降级

每一层挂了都不阻断启动，只是能力降一档。**这是从 `backend/main.py` 的 lifespan 起的规矩**，
基础设施初始化全部包在 `try/except` 里。

| 能力 | 一级 | 二级 | 三级 | 挂了会怎样 |
|---|---|---|---|---|
| 业务数据 | MySQL | — | — | **唯一硬依赖**。连不上则页面显示"MySQL未连接"，但没有它整个系统没有意义 |
| 向量检索 | 本地嵌入式 Qdrant | 远程 Qdrant 服务端 | 本地文件 + numpy 余弦暴力检索 | 推荐质量下降，功能不中断（`backend/qdrant_client.py`） |
| 大模型 | DeepSeek（`DEEPSEEK_API_KEY`） | — | 规则引擎 | 补货/文案/维系建议退回硬编码规则（`backend/llm_client.py`） |

`/api/system/status` 会**如实**回报当前实际生效的是哪一级 —— 不让 UI 替底层撒谎。

---

## 目录结构

```
agent12/
├── start.py                    一键启动（uvicorn reload=True，端口 8001）
├── requirements.txt
├── .env / .env.example         配置（.env 已 gitignore）
├── backend/
│   ├── main.py                 FastAPI 入口、lifespan、前端路由、no-store 中间件
│   ├── database.py             全部 MySQL 操作（pymysql 直连，没有 ORM）
│   ├── models.py               pydantic 请求/响应模型
│   ├── llm_client.py           LLM 封装（指数退避重试 + JSON 自动修复）
│   ├── qdrant_client.py        向量库 + 三级降级
│   ├── api/routes.py           26 个 API 路由
│   ├── agents/                 5 个业务 Agent + 统一 dispatcher
│   └── workflow/               LangGraph 两条 DAG
├── frontend/                   8 个页面，原生 HTML/JS/CSS，无构建
│   ├── js/cashier.js           收银台逻辑
│   └── js/dashboard.js         看板逻辑
└── _check_*.py / _check_*.js   校验脚本（见下）
```

---

## 数据模型

9 张表，`init_database()` 里 `CREATE TABLE IF NOT EXISTS` 一次建好。

| 表 | 作用 |
|---|---|
| `products` | 商品主数据（SKU、条码、进价、零售价、安全库存、补货点） |
| `inbound_records` | **入库批次**。每批带 `remaining_qty`，FIFO 扣减就靠它 |
| `outbound_records` | 出库记录（销售/破损/试用/过期报损/店内消耗） |
| `stock_snapshots` | 库存快照。`current_stock` + 移动平均 `avg_cost` + `total_value` |
| `customers` | 会员（含宠物信息、消费额、到店次数） |
| `grooming_schedule` | 洗护预约 |
| `daycare_records` | 托管签到记录 |
| `daily_metrics` | 日汇总（营收/订单/毛利/新老客），支撑看板的长周期查询 |
| `daily_product_sales` | 商品日销明细，支撑热销榜 |

**两条贯穿全项目的不变量：**

1. **今天不落库。** `daily_metrics` 只存到昨天，今天的数字永远从 `outbound_records`
   实时算。否则"今天"会同时存在于汇总表和流水表，两边一叠加就是双倍。
2. **库存恒等式。** `stock_snapshots.current_stock == Σ inbound_records.remaining_qty
   == 累计入库 − 累计出库`。出库走 FIFO（`ORDER BY inbound_time`），
   入库时 `remaining_qty` 必须写对，否则后续 FIFO 会静默跳过这一批。

**时间口径也是刻意的**：看板的「本月」是 9/1 ~ 9/30（自然月，未来的日期补 0），
不是"往前滚 30 天"；「本周」是周一到周日。滚动窗口会让 x 轴随日期滑动，
用户看到的"本月"每天都不一样。

---

## API 一览

共 26 个路由，全部挂在 `/api` 下。

| 分组 | 路由 |
|---|---|
| 系统 | `GET /system/status` |
| 收银 | `GET /scan/product`、`GET /customer/{id}`、`POST /checkout` |
| 库存 | `GET /stock/all`、`GET /stock/alerts`、`GET /stock/warnings` |
| **入库** | `POST /inbound`（多行进货单）、`GET /inbound/recent` |
| 看板 | `GET /dashboard/summary`、`/trend`、`/top-products`、`/monthly` |
| 客户 | `GET /customers/stats`、`/customers/retention-suggestions` |
| 洗护 | `GET /grooming/today`、`POST /grooming/book`、`GET /grooming/pet-notes` |
| 健康 | `GET /health/alerts` |
| 托管 | `POST /daycare/checkin`、`GET /daycare/today` |
| 内容 | `POST /content/generate` |
| AI | `POST /replenish/analyze`、`POST /rag/analyze` |
| 工作流 | `POST /dag/daily`、`POST /dag/customer` |

看板那 4 个接口里，`summary` / `trend` / `top-products` 接受 `?period=today|week|month|year`；
`monthly` 收的是 `?months=N`（默认 12）。

---

## 校验脚本

项目没有 `tests/` 目录，验证靠顶层的几个临时脚本 —— 它们是**断言，不是肉眼看**，
跑的是真后端和真数据库：

```bash
python _check_inbound.py            # 到货入库：原子性、校验、FIFO、库存恒等式（40 项）
node   _check_inbound_frontend.js   # 入库前端：表单 → 请求体 → 库里真的变了
node   _check_dashboard_frontend.js # 看板前端：切周期、12 个月桶、自然区间对齐
python _repair_wrong_sku.py         # 历史数据冲正（一次性，见脚本内注释）
_dbq.py                             # 上面脚本读写数据库用的小工具
```

前端那两个用 `node:vm` 把页面的内联脚本放进沙箱、DOM 打桩、`fetch` 打真后端，
所以能验到"请求真的发出去了、响应真的渲染了"，而不只是"函数没报错"。

**注意它们发的请求不一样**：

- `_check_inbound.py` **不走 HTTP**，直接 `import` agent 函数在进程内调，
  校验的是数据库这一层，所以不需要服务在跑。
- `_check_inbound_frontend.js` 打 `127.0.0.1:8002`（脚本里把页面的 API 常量替换掉了），
  为的是不干扰你正在浏览器里看着的那个 8001。
- `_check_dashboard_frontend.js` 打 `127.0.0.1:8001`，需要服务在跑。

前两个**会真的写库**，跑完在 `finally` 里把数据还原。跑之前建议先备份。

---

## 开发约定

**前端没有构建步骤**，所以缓存是这里唯一容易踩的坑。改完前端必须让浏览器拿到新文件：

1. **HTML 层面**：`backend/main.py` 的中间件对所有 `.html/.js/.css` 和 9 个页面路径
   发了 `Cache-Control: no-store`，正常情况下刷新即可。
2. **脚本层面**（第二道保险）：`index.html` 和 `dashboard.html` 里的
   `<script src="js/x.js?v=N">`。改了 JS 就 +1。
3. **构建号**：`backend/main.py` 的 `_FRONTEND_BUILD`、`index.html` 的 `?v=`、
   `cashier.js` 的 `CASHIER_BUILD` —— **三处要一致**，不一致就会出现
   "代码明明改了、页面却没变"的假象。收银台顶栏有一枚版本戳，显示 `--` 就是浏览器跑着旧脚本。

`inventory.html` 等页面的 JS 是**内联在 HTML 里**的，所以没有 `?v=` 要改，
但也就没有独立的 `.js` 文件可以单独 reload —— 这是它和其他页面的不一致之处。

**前端的 API 地址是相对路径** `/api`，因为前端和后端是同一个 FastAPI 进程发出来的，
同源即可，所以本地、换端口、部署到服务器都不用改。

> 这里原先 8 个文件里写死的是 `http://127.0.0.1:8001/api`。那是**部署陷阱**：
> 服务器上跑起来后，用浏览器从外面访问，页面里的 JS 会去请求 **`127.0.0.1`——
> 也就是访问者自己的机器**，而不是服务器。现象是页面能显示但数据全空、
> 报"MySQL未连接"，很容易误判成后端没起来。已全部改成 `/api`。

---

## 部署到服务器

下面这套步骤在**全新**的阿里云 ECS 上实测走通过（Alibaba Cloud Linux 3，1.8G 内存）。
按顺序做，**别跳**——漏掉第 0 步和第 2 步的插件选择，都会以很难查的方式失败。

**0. 先加 swap（内存小于 2G 时必做）**

新开的 ECS 常常是 `Swap: 0B`。装依赖时的内存峰值很容易冲过物理内存，届时进程会被
OOM killer **无声杀掉**——只留下一句 `Killed`，不提示内存不足，极难往"内存不够"上想。

```bash
free -h                                # 先看 Swap 那行是不是 0B
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h                                # Swap 应变成 2.0Gi
```

> `fallocate` 若报 `invalid argument`（某些文件系统不支持），改用
> `dd if=/dev/zero of=/swapfile bs=1M count=2048`。

**1. 装 Python 3.11**（**不要动系统自带的 `python3`**，RHEL 系的 `yum`/`dnf` 靠它跑）

```bash
python3 --version        # 低于 3.10 就得先装新的

# Alibaba Cloud Linux 3 / CentOS 8+ / Rocky：
dnf install -y python3.11 python3.11-pip
python3.11 -m venv /opt/petstore-venv

# CentOS 7（仓库里没有 3.10+，用 Miniconda，不用编译）：
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/miniconda3
/opt/miniconda3/bin/conda create -y -n petstore python=3.11
# 之后一律用 /opt/miniconda3/envs/petstore/bin/pip 和 .../bin/python
```

用独立 venv 而不是直接 `pip3.11 install`，是为了不动系统那份 Python 3.11，
将来 `dnf update` 时不会和手装的包打架。代价只是命令要写全路径。

**2. 装 MySQL 8.0**

```bash
dnf install -y mysql-server
systemctl enable --now mysqld
mysql -u root -e "SELECT VERSION();"     # 刚装完 root 通常免密
```

版本必须 **≥ 5.7.8**：`customers` 表用了 `JSON` 类型（`pets` / `tags` /
`preferred_categories`），再老的版本建表就失败。`petstore_db` 库**不用手工建**，
首次启动会 `CREATE DATABASE IF NOT EXISTS` 并灌入种子数据。

设口令时**用 `mysql_native_password`，不要用 8.0 默认的 `caching_sha2_password`**：

```bash
mysql -u root -e "ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '你的口令'; FLUSH PRIVILEGES;"
mysql -u root -p'你的口令' -e "SELECT VERSION();"    # 验证
```

> **为什么必须指定插件**：`requirements.txt` 里没有 `cryptography`，而 PyMySQL 走
> **TCP** 连 `caching_sha2_password` 时需要它，否则直接抛
> `RuntimeError: 'cryptography' package is required for sha256_password or caching_sha2_password auth methods`。
> `mysql_native_password`（老式 SHA1 挑战应答）可以绕开，不用加依赖。
> 但它在 MySQL 8.0.34+ 已标记废弃、**8.4 起被移除**——将来升到 8.4 就得反过来
> 往 `requirements.txt` 里加 `cryptography`。

内存小于 2G 时顺手把 MySQL 占用压下来（`performance_schema` 白吃一百多兆，这套系统用不到）：

```bash
echo '[mysqld]' > /etc/my.cnf.d/zz-petstore-tuning.cnf
echo 'performance_schema = OFF' >> /etc/my.cnf.d/zz-petstore-tuning.cnf
echo 'innodb_buffer_pool_size = 128M' >> /etc/my.cnf.d/zz-petstore-tuning.cnf
echo 'max_connections = 50' >> /etc/my.cnf.d/zz-petstore-tuning.cnf
systemctl restart mysqld
```

`zz-` 前缀是**故意的**：`my.cnf.d` 按字母序读取，排在最后才会覆盖前面文件的同名项。
放在这个独立文件里而不是改原文件，将来想撤直接删掉即可。

**3. 建 `.env`**

`.env` 被 `.gitignore` 挡住了，**clone 下来是没有的**。但**不必照抄 `.env.example` 的全部键**——
代码里每个键都有可用的默认值（见 `backend/database.py:10-14`、`llm_client.py:9-11`、
`qdrant_client.py:8-12`），**只有 `MYSQL_PASSWORD` 的默认值 `123456` 必须覆盖**：

```bash
echo 'MYSQL_PASSWORD=你的口令' > .env
```

`DEEPSEEK_API_KEY` 建议**先留空**：不填时 AI 功能自动降级到规则引擎，系统照常运行。
先把基础功能验证通过、再加 key，能把"数据库连不上"和"key 不对"两类问题分开排查。

**4. 装依赖**（国内服务器建议走镜像，别直连 PyPI）

```bash
/opt/petstore-venv/bin/pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
```

**5. 用 systemd 托管**

别在前台跑 `python start.py`——关掉终端窗口进程就没了。存成
`/etc/systemd/system/petstore.service`，**把两处路径换成你自己的仓库位置**：

```ini
[Unit]
Description=Pet Store Management System
After=network.target mysqld.service

[Service]
WorkingDirectory=/root/Pet-Business-Management-System
ExecStart=/opt/petstore-venv/bin/python start.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now petstore
systemctl status petstore --no-pager
```

`WorkingDirectory` 和 `ExecStart` **必须是绝对路径**——systemd 没有"当前目录"的概念，
写相对路径服务会静默起不来（单元文件语法错误 systemd 不一定报，很难查）。

**6. 放行端口**：阿里云**安全组**加一条 8001 入方向规则，服务器上再看 `firewalld` / `iptables`。

> **不要放行 3306。** 后端连 MySQL 走的是 `localhost`，不需要外部访问；
> 放行了等于把数据库直接摆到公网上。

跑起来之后验证：

```bash
curl -s localhost:8001/api/system/status   # 看降级层级对不对
```

> ⚠️ **`Application startup complete` 不能证明 MySQL 通了。**
> `backend/main.py` 的 lifespan 把初始化全包在 `try/except` 里（三层降级的设计使然），
> MySQL 失败时只打印一行 `[警告] MySQL 初始化失败` 然后**照常启动**。
> 所以必须独立验证，不能看服务状态就下结论：
>
> ```bash
> mysql -u root -p'口令' -e "SHOW TABLES;" petstore_db   # 应有 9 张表
> curl -s localhost:8001/api/stock/all | head -c 200      # 应有商品 JSON
> ```

浏览器访问 `http://<公网IP>:8001`，如果页面出来了但数据全空，
先看浏览器开发者工具的 Network —— 请求打到 `127.0.0.1` 就说明前端还是老版本。

> **另一个容易误判的现象**：8 个页面都从公网 CDN 拉 `cdn.tailwindcss.com`、
> `cdn.jsdelivr.net`（Chart.js）、`cdnjs.cloudflare.com`（Font Awesome）。
> 这些是**浏览器**去拉的，不占服务器带宽，但客户端网络到这几个域不稳时，
> 页面会变成**没样式的白板**——HTML 和数据其实都正常。
> 出现白板先看 Network 里这几个域是不是红了，别又当成后端没起来。
> 要彻底摆脱，就把这三个文件下载到 `frontend/vendor/` 改成本地引用。

> 这套系统**没有任何登录鉴权**，CORS 还是 `allow_origins=["*"]`。
> 挂公网等于谁扫到 IP 都能调 `/api/checkout` 写库，当演示用可以，别放真实经营数据。

---

## 已知边界

这些是**已知且有意留着**的，不是没想到：

- **入库没有冲正/撤销。** 录错一笔目前只能直接改库。真上线必须补冲正单，
  这是这套系统最大的遗留缺口。
- **`process_outbound` 有两个既有缺陷**：`quantity=0` 会产生空 `deductions`
  然后 `deductions[0]` 抛 `IndexError`；`avg_cost` 为 NULL 时除零。正常调用路径不会触发
  （结算最少 1 件），但没有防御。
- **AI 补货分析和入库没接上。** `/api/replenish/analyze` 在 `inventory.html` 里
  发的是空 payload（`low_stock: []`），LLM 拿不到真实库存，只能凭空气编；
  「建议补货 20 件」也没有按钮可以点。看板页的同类功能是真去 `/api/stock/all` 攒了数据的，
  两个页面一个真问一个假问。
- **`stock_snapshots.min_expiry_date` 是遗留死列**，从没被写过也从没被读过；
  效期预警走的是 `inbound_records.expiry_date + remaining_qty`。
- **`_replenish_plan()` 是死代码**，和 `/api/replenish/analyze` 字段名还不一致
  （`urgent`/`plan` vs `urgent_items`/`plan_items`），是两套互不相干的实现。
- **没有 `suppliers` 表**，供应商是自由文本 `VARCHAR(16)`。
- **CORS 是 `allow_origins=["*"]`**，仅适合本地开发。
- **`.env` 里是明文凭据。** 已被 `.gitignore` 挡住，但别把这个文件夹直接打包发人。

---

## License

未指定。这是个人作品集项目。
