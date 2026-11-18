# MailVerify — 完整方案

> 📧 **"Clean your email list before sending. Don't pay for bounces."**
>
> 版本：v1.0 | 2026-11-18

---

## 一、产品定义

### 1.1 是什么

一个 **Email Verification & List Cleaning Service**（邮件验证 & 列表清洗服务）。用户输入单个邮箱或上传 CSV 列表，系统通过 4 步验证（格式 → MX → SMTP 握手 → 反查）返回每个邮箱的真实状态（有效/无效/风险）。

### 1.2 为什么能赚钱

| 残酷事实 | 数字 |
|----------|------|
| 平均邮件列表 **22.5% 是无效的** | ZeroBounce 2024 数据 |
| SendGrid 报告发送邮件时 **9% 会 bounce** | 每 1000 封邮件 = 90 封白送钱 |
| Bounce 率过高会 **被 ESP 降权** | Gmail/Outlook 直接进垃圾箱 |
| 一个 10 万封的列表清洗后 **能省 $180/月** 发送成本 | 按 SendGrid $0.001/封 |

### 1.3 核心功能 — 批量优先

**单邮箱验证只是 demo。批量才是付费用户的核心需求。**

#### 🎯 核心卖点：**批量验证**

```
用户上传 10,000 封邮件的 CSV
    ↓
系统自动：
  1. 解析 CSV → 提取 email 列
  2. asyncio 并发 50 路 → 4 步验证（格式→MX→SMTP→catch-all）
  3. 每封 1-3 秒 → 10,000 封 ≈ 3-5 分钟
  4. 实时进度条（0-100%）
  5. 下载清洗后的 CSV（valid / invalid / risky 分三个文件）
  6. 统计报表：valid 率、invalid 原因分布、top invalid 域名
```

| 批量特性 | 说明 | 竞品做得到吗 |
|---------|------|-------------|
| **CSV/XLSX 上传** | 支持任何列名（自动识别 email 列） | ✅ 都有 |
| **10 万封级处理** | 大列表不分片，直接一个文件搞定 | ⚠️ 部分有文件大小限制 |
| **asyncio 高并发** | 50 路 SMTP 同时跑，10k 封 3-5 分钟 | ✅ |
| **实时进度查询** | GET /api/result/:jobId → processed / total | ❌ **很多竞品只返回 "processing" 不告诉进度** |
| **清洗后三文件下载** | valid.csv + invalid.csv + risky.csv | ⚠️ 部分合并成一个 |
| **清洗后统计报表** | valid 率、invalid 原因分布、top invalid 域名 | ❌ **没人做** |
| **API 批量模式** | POST 100 封 JSON 数组，API 直接验 | ⚠️ 只有高级版有 |
| **历史任务保存** | 30 天内可回看之前的批量结果 | ❌ **基本没人做** |

#### 其他功能（辅助）

| 功能 | 说明 |
|------|------|
| **Single Verify** | 单邮箱验证 — landing page demo 用，吸引用户注册 |
| **SMTP Handshake** | 真·连接邮件服务器问"这个邮箱在不在"（核心算法） |
| **Role-based Detection** | 识别 support@ / admin@ / info@ 等角色邮箱（可选项） |
| **Disposable Detection** | 识别 temp-mail.org / 10minutemail 等一次性邮箱 |
| **Catch-all Detection** | 识别 catch-all 域名（任何地址都收）— **独有** |
| **Greylisting Handling** | 识别 greylisting（临时拒绝但不是真无效）— **独有** |

### 1.4 与竞品的差异化

| | ZeroBounce | Hunter.io | Bouncer | **MailVerify 我们** |
|---|---|---|---|---|
| SMTP 验证 | ✅ | ✅ | ✅ | ✅ |
| 批量 CSV | ✅ | ✅ | ✅ | ✅ |
| Role detection | ✅ | ❌ | ❌ | ✅ |
| Disposable detection | ✅ | ❌ | ✅ | ✅ |
| **Catch-all detection** | ❌ | ❌ | ❌ | ✅ **独有** |
| **Greylisting handling** | ❌ | ❌ | ❌ | ✅ **独有** |
| 免费额度 | 100 封 | 25 封/月 | 100 封 | **100 封/天** |
| API 免费 | ❌ | ❌ | ❌ | ✅ **免费版也有** |
| 起步价 | $19/月 | $49/月 | $16/月 | **$4.99/月** |

**一句话差异：别人告诉你"这个邮箱无效"，我们告诉你"这个邮箱是 catch-all 域名的，可能有风险" + 免费额度更大 + API 免费。**

---

## 二、技术架构（Cloudflare Pages + Render.com）

### 2.1 为什么用双栈

| 组件 | 为什么不用 Cloudflare Pages Functions | 为什么用 Render.com |
|------|-------------------------------------|-------------------|
| SMTP 握手 | Workers 不能开 TCP socket（只有 HTTP fetch） | Python asyncio 原生支持 asyncio.open_connection() |
| 批量处理 | Workers 30s timeout，批量 1000 封超时限 | Python + asyncio 异步并发，1000 封 1-2 分钟 |
| DNS MX 查询 | Workers 只能 fetch DNS over HTTPS | Python dnspython 原生支持 |

### 2.2 完整架构图

```
用户浏览器
    │
    ├── Landing Page ──────────────────────────────┐
    ├── 单邮箱验证 → POST /api/verify ──────────────┤
    ├── CSV 批量上传 → POST /api/batch ──────────────┤
    │                                                │
    ▼                                                ▼
Cloudflare Pages (前端 + API 代理)
    │
    ├── index.html          Landing page
    ├── dashboard.html      用户仪表盘（历史、配额）
    │
    └── functions/api/
        ├── verify.js       转发到 Render 后端
        ├── batch.js        转发到 Render 后端
        ├── webhook.js      Creem 支付回调 → 升级 Pro
        └── core/proxy.js   统一代理 + CORS + 限流
    │
    ▼ (HTTPS fetch)
Render.com (后端 Python — mailverify-backend)
    │
    ├── POST /verify        单邮箱验证
    │   ├─ Step 1: 格式检查 (regex)
    │   ├─ Step 2: MX 检查 (dnspython)
    │   ├─ Step 3: SMTP 握手 (asyncio + aiosmtpd)
    │   ├─ Step 4: PTR 反查 + Greylisting 检测
    │   └─ 返回: {status, reason, score}
    │
    ├── POST /batch         批量验证
    │   ├─ 解析 CSV
    │   ├─ asyncio.Semaphore 控制并发 50
    │   ├─ 逐个 async verify
    │   └─ 返回 JSON + 下载 CSV 结果
    │
    ├── GET /result/{jobId}  查询批量任务状态
    │
    └── PostgreSQL (Render 免费层)
        ├── users           email + plan + quota
        ├── jobs            batch 任务元数据
        └── results         批量验证结果
```

### 2.3 核心算法：4 步验证

```
输入: "test@example.com"
      ↓
Step 1 — 格式检查
  regex: ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$
  通过 → 继续；失败 → status="invalid", reason="format"
      ↓
Step 2 — MX 检查 (dnspython)
  dns.resolver.resolve("example.com", "MX")
  有 MX 记录 → 继续；没有 → status="invalid", reason="no_mx"
  同时检查: disposable 域名黑名单 (10minutemail, temp-mail.org, ...)
  命中 → status="disposable"
      ↓
Step 3 — SMTP 握手 (asyncio)
  async with asyncio.open_connection(host, 25) as (reader, writer):
    220 ← welcome
    HELO mailverify.app
    250 ← ok
    MAIL FROM: <verify@mailverify.app>
    250 ← ok
    RCPT TO: <test@example.com>
    ↓
    服务器返回:
      250 → status="valid" ✅
      550 User unknown → status="invalid", reason="not_found" ❌
      554 Mailbox full → status="risky", reason="full" ⚠️
      450/451/452 Greylisting → status="risky", reason="greylisted" ⏳
      421 Service not available → status="risky", reason="deferred" ⏳
      连接超时 → status="unknown", reason="timeout"
      连接拒绝 → status="invalid", reason="mx_blocked"
      ↓
Step 4 — Catch-all 检测
  同一域名发 RCPT TO: <random12345@example.com>
  如果返回 250 → status="catchall_risk" ⚠️
  （任何地址都收 = 无法确认真实有效）
      ↓
最终: {
  email: "test@example.com",
  status: "valid|invalid|risky|unknown|catchall_risk",
  reason: "not_found|greylisted|disposable|...",
  score: 0-100,
  checks: {format:true, mx:true, smtp:true, catchall:false}
}
```

### 2.4 技术栈明细

| 组件 | 技术 | 说明 |
|------|------|------|
| **前端** | Cloudflare Pages | 纯 HTML/CSS/JS，零构建 |
| **API 代理** | Cloudflare Pages Functions | JS Worker，限流 + 转发 |
| **后端** | Python 3.11 + FastAPI | async 高并发 |
| **SMTP** | asyncio + aiosmtpd（自实现握手，不用第三方库） | 可控性强 |
| **DNS** | dnspython | MX / PTR 查询 |
| **批量** | asyncio.Semaphore(50) | 并发 50，不被封 |
| **数据库** | PostgreSQL（Render 免费层 100MB） | 用户 + quota + 批量任务 |
| **支付** | Creem（Pages Functions webhook） | 复用现有 |
| **域名** | mailverify.app | $8/年 Dynadot |

### 2.5 Render.com 选型理由

| 备选 | 免费层 | Python asyncio | 数据库 | 休眠 |
|------|--------|---------------|--------|------|
| **Render.com** ✅ | $0（750 小时/月） | ✅ | ✅ PostgreSQL 100MB | 15 分钟不活动后休眠 |
| Fly.io | 3 台共享机 | ✅ | ❌ 无免费 DB | 不休眠但免费额度少 |
| Railway | $5 起步 | ✅ | ✅ | 不休眠但要付费 |
| Vercel Serverless | 100 次/天 | ❌ 30s timeout | ❌ | 不适合长任务 |
| Google Cloud Run | $0 | ✅ | ✅ | 会休眠 |

Render 免费层 750 小时/月 = 可以跑 1 个服务 24/7（720 小时/月）+ 另一个 30 小时。**起步完全够用。**

---

## 三、API 设计

### 3.1 端点一览

| 方法 | 路径 | 功能 | 层 |
|------|------|------|-----|
| **POST** | `/api/verify` | 单邮箱验证 | Pages → Render |
| **POST** | `/api/batch` | CSV 批量上传 | Pages → Render |
| **GET** | `/api/result/:jobId` | 查批量任务状态 | Pages → Render |
| **POST** | `/api/checkout` | Creem 支付跳转 | Pages (Creem API) |
| **POST** | `/api/creem-webhook` | 支付回调 | Pages → Render (升级用户) |
| **GET** | `/api/quota?email=xxx` | 查用户剩余配额 | Pages → Render |

### 3.2 POST /api/verify

```json
// Request (Cloudflare Pages → 转发到 Render)
{
  "email": "test@example.com",
  "timeout": 10          // 可选，默认 10s
}

// Response (200)
{
  "email": "test@example.com",
  "status": "valid",       // valid | invalid | risky | unknown | catchall_risk | disposable
  "reason": null,          // not_found | greylisted | disposable | no_mx | format | ...
  "score": 95,             // 0-100
  "checks": {
    "format": true,
    "mx": true,
    "smtp": true,
    "catchall": false,
    "disposable": false,
    "role_based": false
  },
  "mx_records": [
    {"priority": 10, "exchange": "mail.example.com"}
  ],
  "smtp_response": "250 OK",
  "checked_at": "2026-11-18T12:00:00.000Z",
  "latency_ms": 842
}

// Example: invalid email
{
  "email": "fake@example.com",
  "status": "invalid",
  "reason": "not_found",
  "score": 15,
  "checks": {"format": true, "mx": true, "smtp": false, ...},
  ...
}

// Example: catch-all risk
{
  "email": "anything@example.com",
  "status": "catchall_risk",
  "reason": null,
  "score": 60,
  "note": "Domain accepts all addresses. Cannot confirm validity.",
  ...
}
```

### 3.3 POST /api/batch

```
Content-Type: multipart/form-data
Body: file=@list.csv

// Response (202 Accepted)
{
  "job_id": "batch_a1b2c3d4",
  "total": 5000,
  "processed": 0,
  "status": "processing"
}
```

### 3.4 批量 CSV 格式

```
input_email,status,reason,score,notes
john@gmail.com,valid,,98,
support@company.com,valid,,92,Role-based
admin@temp-mail.org,disposable,disposable,5,
fake@yahoo.com,invalid,not_found,12,
anything@catchall.com,catchall_risk,,58,Domain accepts all
test@greylisted.io,risky,greylisted,71,Try again later
```

---

## 四、盈利模型

### 4.1 定价

| 版 | 价格 | 配额 | API | 并发 | 额外 |
|---|------|------|-----|------|------|
| **Free** | $0 | **100 封/天** | ✅ 免费 | 1 | 单邮箱验证 |
| **Pro** | **$4.99/月** | 5,000 封/月 | ✅ | 10 | 批量 CSV + API |
| **Business** | **$14.99/月** | 25,000 封/月 | ✅ | 50 | 优先队列 + 团队 |
| **Enterprise** | 按需 | 无限 | ✅ | 不限 | 白标 + SLA |

### 4.2 为什么比竞品便宜

| 竞品 | 起步价 | 免费额度 |
|------|--------|---------|
| ZeroBounce | $19/月 | 100 封（一次） |
| Hunter.io | $49/月 | 25 封/月 |
| Bouncer | $16/月 | 100 封 |
| **MailVerify** | **$4.99/月** | **100 封/天** |

### 4.3 支付流程

```
用户点 "Go Pro"
    ↓
POST /api/checkout (Creem)
    ↓
Creem checkout URL → 浏览器跳转
    ↓
支付成功 → Creem POST → /api/creem-webhook (Pages Functions)
    ↓
Pages Functions → POST Render /upgrade-user (email + plan)
    ↓
Render PostgreSQL → users table 更新 plan + quota
    ↓
用户刷新 dashboard → 看到 Pro 配额
```

### 4.4 成本结构

| 项目 | 月成本 | 说明 |
|------|--------|------|
| Cloudflare Pages | $0 | 免费额度 100k req/天 |
| Render 后端 | **$0** | 免费层 750 小时/月 |
| Render PostgreSQL | **$0** | 免费层 100MB |
| Mailgun（通知） | $0 | 10k/月免费 |
| 域名 | $0.67 | $8/年平摊 |
| Creem 手续费 | 5% + $0.30 | 从收入扣 |
| **合计** | **$0.67** | 起步几乎零成本 |

### 4.5 收入预测（保守）

| 阶段 | 时间 | 月验证量 | 付费率 | MRR |
|------|------|---------|--------|-----|
| 初期 | 3 月 | 10k 封 | 5% → 50 用户 | $249 |
| 中期 | 6 月 | 50k 封 | 7% → 350 用户 | $1,746 |
| 稳定 | 12 月 | 200k 封 | 8% → 1600 用户 | $7,984 |

---

## 五、竞品 VS 我们

### 5.1 竞品全览

| 竞品 | 起步价 | 月活 | Catch-all | Greylist | API 免费 |
|------|--------|------|-----------|----------|---------|
| **ZeroBounce** | $19/月 | 100 万+ | ❌ | ❌ | ❌ |
| **Hunter.io** | $49/月 | 200 万+ | ❌ | ❌ | ❌ |
| **Bouncer** | $16/月 | 小众 | ❌ | ❌ | ❌ |
| **NeverBounce** | $10/月 | 小众 | ❌ | ❌ | ❌ |
| **MailTester** | 免费（单次） | 小众 | ❌ | ❌ | ❌ |
| **我们** | **$4.99/月** | 0 → | ✅ | ✅ | ✅ |

### 5.2 关键差异化

| | 竞品 | 我们 |
|---|---|---|
| Catch-all 检测 | ❌ 没人做 | ✅ **核心独有** — 告诉你这个域名任何邮箱都收 |
| Greylisting 处理 | ❌ 一律报 invalid | ✅ **区分处理** — 告诉你"临时拒绝，过几小时再试" |
| 免费额度 | 100 封（一次性） | **100 封/天**（每天回来都能用） |
| API | 付费才给 | **免费版也有 API** |
| 价格 | $16-49/月 | **$4.99/月起** |

---

## 六、推广策略

### 6.1 冷启动（前 30 天）

| 渠道 | 怎么做 | 预期 |
|------|--------|------|
| **BetaList** | Submit — "MailVerify: Email verification with catch-all + greylisting detection" | 200-500 早期用户 |
| **Reddit** | r/emailmarketing, r/smallbusiness, r/SaaS | 100-300 访客 |
| **HN Show HN** | "Show HN: MailVerify — Email verification that detects catch-all domains and greylisting" | 2000+ 访客 |
| **Twitter/X** | Thread: "Why your email bounces 9% of the time — and how to fix it for $4.99/month" | 500-1000 访客 |
| **Product Hunt** | Day 2 launch（BetaList 之后） | 500+ 用户 |

### 6.2 SEO 长期

| 关键词 | 难度 | 目标 |
|--------|------|------|
| "email verification" | 🔥🔥🔥🔥🔥 | 太难（ZeroBounce/Hunter 权重大） |
| "email verifier tool" | 🔥🔥🔥 | Top 10 |
| "bulk email checker" | 🔥🔥🔥 | Top 5 |
| "catch-all email detector" | 🔥🔥 | **Top 1 目标（没人做）** |
| "greylisting email check" | 🔥🔥 | **Top 1 目标** |
| "zero bounce alternative" | 🔥🔥 | Top 1 |

### 6.3 病毒式增长

- 批量验证后："Share your results — I cleaned 5000 emails, removed 1200 invalid ones"
- API 用户："Built with MailVerify — sign up for free API access"

---

## 七、里程碑

### Phase 1 — MVP（1 周）

**Render.com Python 后端（核心）**
- [ ] 注册 Render.com 账号
- [ ] 新建 Web Service — Python 3.11 + FastAPI
- [ ] 写 `verify_email()` 核心函数（4 步验证）
- [ ] 写 `batch_verify()` 批量 + asyncio.Semaphore
- [ ] PostgreSQL 数据库 schema
- [ ] CORS 配置（允许 mailverify.app）
- [ ] 部署 Render → 拿 `onrender.com` URL

**Cloudflare Pages（前端 + API 代理）**
- [ ] Landing page（单邮箱验证 demo + 定价）
- [ ] Pages Functions API proxy
- [ ] Rate limiting（Free 版 100/天）
- [ ] `/api/checkout` + `/api/creem-webhook`

**本地测试**
- [ ] 单邮箱验证（有效/无效/greylist/catch-all/disposable）
- [ ] 批量 100 封 CSV 上传
- [ ] API 免费版限流

### Phase 2 — 域名 + DNS（1 天）

- [ ] 购买 mailverify.app（Dynadot $8）
- [ ] Cloudflare Add site → mailverify.app
- [ ] 阿里云改 NS
- [ ] CNAME → Pages
- [ ] Pages Functions 设置环境变量（RENDER_BACKEND_URL）
- [ ] Redeploy production
- [ ] Creem product + webhook 配置

### Phase 3 — 推广（1 周）

- [ ] BetaList submit
- [ ] HN Show HN
- [ ] Reddit 发帖
- [ ] Twitter thread
- [ ] Product Hunt 提交

---

## 八、风险 + 退路

| 风险 | 概率 | 应对 |
|------|------|------|
| **SMTP 被封 IP** | 中 | Render 用住宅 IP？不行。加 Cloudflare "Email Verification" service？或者用第三方 SMTP relay（SendGrid $0.001/封）作为 fallback |
| **大邮箱服务商（Gmail/Outlook）不回应 SMTP RCPT TO** | 高 | Gmail 从不回应 RCPT TO。标记为 "unknown" 而不是 "valid/invalid"，告诉用户"Gmail 不允许精确验证" |
| **Render 免费层休眠** | 低 | 15 分钟不活动后冷启动。加 cron-job.org 每分钟 ping 一下 `/health` endpoint 保持唤醒 |
| **没人付费** | 中 | 先做免费版积累用户 + SEO。API 免费额度吸引开发者集成 → 他们用着用着就付费升级 |
| **Catch-all 检测成为竞品标配** | 低 | 我们先做 6-12 个月，SEO 抢 "catch-all email detector" 关键词 |

### 退路

**最坏情况：月活 200，月入 $50**

- 成本 ≈ $0.67/月（域名）
- Render 免费层继续跑
- 把 catch-all 检测开源成 Python 包 `mailverify-core`
- 或者只做单邮箱免费验证，不做批量

---

## 九、目录结构

```
E:\mailverify\
├── docs/
│   └── plan.md              ← 本方案
│
├── frontend/                 (Cloudflare Pages)
│   ├── index.html            (landing + 单邮箱 demo)
│   ├── dashboard.html        (历史 + 配额 + 批量上传)
│   ├── css/style.css
│   ├── js/app.js
│   └── functions/api/
│       ├── verify.js         (代理 → Render)
│       ├── batch.js          (代理 → Render)
│       ├── proxy.js          (统一代理逻辑 + CORS + 限流)
│       ├── checkout.js       (Creem)
│       ├── creem-webhook.js  (Creem 回调)
│       └── quota.js          (查用户配额)
│
└── backend/                  (Render.com Python FastAPI)
    ├── main.py               (FastAPI app + routes)
    ├── verify.py             (核心 4 步验证算法)
    ├── batch.py              (批量 + asyncio 并发)
    ├── database.py           (PostgreSQL 连接 + schema)
    ├── disposable.py         (一次性邮箱域名黑名单)
    ├── requirements.txt      (fastapi, uvicorn, dnspython, asyncio)
    ├── render.yaml           (Render 部署配置)
    └── README.md
```

---

## 十、下一步（等方案确认）

1. 你看完方案 → OK → 开工 Phase 1（先 Python 后端，验证 SMTP 能跑通）
2. 有要改的 → 告诉我改哪里
3. 暂停 → 先处理 WebHound 或 DiskWarden/RecoverMill Dashboard 设置

---

## 附录 A：SMTP 状态码速查

| 码 | 含义 | 我们的判定 |
|----|------|-----------|
| 250 | OK | ✅ valid |
| 251 | User not local, forward | ✅ valid |
| 450 | Mailbox busy (greylist) | ⏳ risky, greylisted |
| 451 | Local processing error | ⏳ risky, deferred |
| 452 | Insufficient system storage | ⚠️ risky, mailbox_full |
| 421 | Service not available, closing | ⏳ risky, deferred |
| 550 | User unknown | ❌ invalid, not_found |
| 551 | User not local | ❌ invalid, not_found |
| 552 | Mailbox full | ⚠️ risky, mailbox_full |
| 553 | Mailbox name invalid | ❌ invalid, bad_syntax |
| 554 | Transaction failed | ❌ invalid |

## 附录 B：Catch-all 检测原理

```python
# 同一域名发两次 RCPT TO
real_response = smtp_rcpt("real_user@example.com")    # 250 或 550
fake_response = smtp_rcpt("zzzzz_random123@example.com")

# 如果 fake 也返回 250 → catch-all 域名！
# （任何地址都收 = 无法确认真实邮箱是否有效）
if fake_response.code == 250:
    status = "catchall_risk"
    note = "Domain accepts all addresses. Real validation impossible."
```

## 附录 C：Greylisting 原理

```python
# Greylist 服务器临时拒绝未知发件人 1-3 小时
# 正常发件人会自动重试，但 SMTP 验证是单次的

# 关键区别：
#   450 Greylist     → ⏳ 临时拒绝，不是真无效（告诉用户稍后再试）
#   550 User Unknown → ❌ 真无效（永久）
#   421 Service Down → ⏳ 临时，服务器维护
```
