# PennyPilot

智能记账 Web 应用（Vue 3 + FastAPI + PostgreSQL）。已覆盖登录、分类、支付方式、日常收支、往来账户、每日结算，以及 AI 自然语言记账与周期分析。

## 快速启动 PostgreSQL

1. 复制环境变量模板并修改密码：

   ```bash
   cp .env.example .env
   ```

2. 启动数据库：

   ```bash
   docker compose up -d db
   docker compose ps
   ```

数据库默认监听 `localhost:5432`，库名、用户和密码可通过 `.env` 调整。首次启动会执行 `backend/db/init/` 中的 SQL；后续表结构由后端迁移工具（Alembic）管理。

## 后端（开发模式）

进入后端目录并安装依赖：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

后端使用根目录 `.env` 中的 `PENNYPILOT_DATABASE_URL`。如果从容器内连接数据库，应将主机名改为 `db`；从宿主机运行则使用 `localhost`。

`PENNYPILOT_DATABASE_URL`、`PENNYPILOT_SECRET_KEY` 等带前缀变量是推荐写法；为兼容旧配置，`DATABASE_URL`、`SECRET_KEY` 等无前缀变量也可以使用。修改 SQLAlchemy 模型后，可用下面的命令生成迁移：

```bash
cd backend
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

如果数据库是在引入 Alembic 之前由旧版本创建的，请先备份并确认现有表结构，再执行 `alembic stamp head` 标记当前结构；全新数据库直接执行 `alembic upgrade head` 即可。

运行基础检查：

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

## 前端（开发模式）

```bash
cd frontend
npm install
npm run dev
```

Vite 会把 `/api` 和 `/health` 代理到本机的 `127.0.0.1:8000`。首次注册会自动创建常用收支分类，以及微信、支付宝、现金、银行转账和 POS 刷卡等支付方式。

## 生产部署（ledger.gitdo.net）

生产 Compose 栈包含 PostgreSQL、FastAPI 后端和 nginx 静态前端。数据库、后端和前端端口都只绑定到宿主机 `127.0.0.1`，公网流量应由宿主机 Caddy 终止 TLS 后转发。这样 PostgreSQL 不会直接暴露到公网，浏览器也始终使用同源 `/api` 请求。

### 1. 准备环境变量

开发环境可以在仓库根目录执行 `cp .env.example .env`。生产环境不要把密钥放在代码目录，建议使用只有 root 可读的 Compose 环境文件：

```bash
install -d -m 700 /etc/pennypilot
install -m 600 .env.example /etc/pennypilot/compose.env
sudoedit /etc/pennypilot/compose.env
openssl rand -hex 32
```

将生成的随机值和数据库强密码写入 `/etc/pennypilot/compose.env`。下面的 Compose 命令都通过 `--env-file /etc/pennypilot/compose.env` 显式读取该文件；不要把生产密钥复制回仓库的 `.env`。

编辑 `/etc/pennypilot/compose.env`，至少修改下面几项：

```dotenv
POSTGRES_PASSWORD=<强随机密码>
PENNYPILOT_SECRET_KEY=<上面命令生成的随机值>
PENNYPILOT_APP_ENV=production
PENNYPILOT_COOKIE_SECURE=true
PENNYPILOT_CORS_ORIGINS=https://ledger.gitdo.net
PENNYPILOT_TRUSTED_HOSTS=ledger.gitdo.net,localhost,127.0.0.1
# 先用 docker network inspect 确认实际网段，再填写 Docker 代理网段。
PENNYPILOT_TRUSTED_PROXY_IPS=127.0.0.1,::1,172.20.0.0/16

# AI 可选配置（不填写 API Key 也可使用本地规则降级）
PENNYPILOT_AI_ENABLED=true
PENNYPILOT_AI_BASE_URL=https://api.openai.com
PENNYPILOT_AI_MODEL=gpt-4o-mini
# PENNYPILOT_AI_API_KEY=<可选；也可在网页设置中按用户加密保存>
# 备用通道默认走同一网关的备用模型；也可改成独立供应商。
PENNYPILOT_AI_FALLBACK_BASE_URL=https://api.openai.com
PENNYPILOT_AI_FALLBACK_MODEL=gpt-4o-mini
# PENNYPILOT_AI_FALLBACK_API_KEY=<可选；留空则默认沿用主通道密钥>
```

`POSTGRES_PASSWORD` 最好使用字母、数字和 `-_`，以便在 Compose 自动生成容器内数据库 URL 时不需要额外 URL 编码。若数据库已经在别处运行，可设置 `PENNYPILOT_CONTAINER_DATABASE_URL` 覆盖该 URL；使用现有数据卷时，URL 中的密码必须与数据库角色密码一致，同时保持 `POSTGRES_PASSWORD` 与其一致，避免未来新卷初始化时出现认证不匹配。

### 2. 构建并启动应用

```bash
docker compose --env-file /etc/pennypilot/compose.env up -d --build --wait --wait-timeout 180
docker compose --env-file /etc/pennypilot/compose.env ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8080/healthz
```

后端容器启动时会先执行 `alembic upgrade head`，成功后才启动 Uvicorn；因此首次启动或升级时无需手动进入容器迁移。`postgres_data` 卷会保留现有数据，不要使用 `down -v`，除非明确要删除数据库。

### AI 配置与容器重建

用户在网页“设置”中保存的 AI 主通道和备用通道配置（接口地址、模型及 API Key）存放在 PostgreSQL 的 `ai_configs` 表中，不存放在前端容器文件系统里。只要保留 `postgres_data` 数据卷，重新构建或替换前后端容器不会清空这些配置。

API Key 在数据库中以密文保存，密钥加密依赖 `PENNYPILOT_SECRET_KEY`。因此每次启动、升级或重建生产容器，都必须使用同一个环境文件：

```bash
docker compose --env-file /etc/pennypilot/compose.env up -d --build --wait --wait-timeout 180
```

不要直接运行不带 `--env-file` 的生产 Compose 命令，否则可能加载默认配置，导致无法解密已有 API Key 或使后端拒绝启动。除非已经完成密钥轮换和数据迁移，否则不要修改 `PENNYPILOT_SECRET_KEY`；`docker compose down -v` 也会删除数据库中的用户配置。

### 3. 配置 Caddy HTTPS

仓库提供了独立站点片段 [deploy/Caddyfile](deploy/Caddyfile)，只包含 `ledger.gitdo.net`，不会覆盖已有站点。确认 DNS 的 A 记录已经指向本机，并确保防火墙放行 TCP 80/443 后，将它导入宿主机 Caddy 主配置（推荐使用 `import`）：

```bash
# Caddy 以 caddy 用户运行，先把 /root 下的片段复制到它可读的位置。
install -m 644 deploy/Caddyfile /etc/caddy/pennypilot.caddy
grep -Fqx 'import /etc/caddy/pennypilot.caddy' /etc/caddy/Caddyfile || \
  printf '\nimport /etc/caddy/pennypilot.caddy\n' >> /etc/caddy/Caddyfile
```

主配置中实际加入的 Caddy 指令是：

```caddyfile
import /etc/caddy/pennypilot.caddy
```

然后验证并重载：

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

Caddy 会自动申请和续期 `ledger.gitdo.net` 的证书，并将 `/api/*`、`/health` 代理到 `127.0.0.1:8000`，其余路径代理到 `127.0.0.1:8080`。浏览器访问 `https://ledger.gitdo.net` 即可。

### 4. 运行状态和日志

```bash
docker compose --env-file /etc/pennypilot/compose.env ps
docker compose --env-file /etc/pennypilot/compose.env logs -f --tail=100 backend
docker compose --env-file /etc/pennypilot/compose.env logs -f --tail=100 frontend
docker compose --env-file /etc/pennypilot/compose.env logs -f --tail=100 db
```

上线前请确认 `PENNYPILOT_SECRET_KEY` 不是示例值、`PENNYPILOT_COOKIE_SECURE=true`，并先完成一次数据库备份和恢复演练。生产环境的 `/etc/pennypilot/compose.env` 应保持 `600` 权限；开发用的 `/root/PennyPilot/.env` 也不要提交到版本库。

### 5. 自动启动、备份与恢复

仓库还提供了 Docker Compose 自启动和每日备份的 systemd 单元。确认路径和 Docker 安装位置无误后执行：

```bash
install -m 644 deploy/systemd/pennypilot-compose.service /etc/systemd/system/
install -m 644 deploy/systemd/pennypilot-backup.service /etc/systemd/system/
install -m 644 deploy/systemd/pennypilot-backup.timer /etc/systemd/system/
install -m 644 deploy/systemd/pennypilot-settlement.service /etc/systemd/system/
install -m 644 deploy/systemd/pennypilot-settlement.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pennypilot-compose.service
systemctl enable --now pennypilot-backup.timer
systemctl enable --now pennypilot-settlement.timer
systemctl list-timers pennypilot-backup.timer
systemctl list-timers pennypilot-settlement.timer
```

页面显示、日期输入和业务自然日统一使用北京时间（Asia/Shanghai，UTC+8）。日结定时器默认按北京时间每日 00:30 运行，生成前一北京自然日的快照；任务使用唯一的“用户 + 日期”键，可安全重复执行。数据库和 API 时间戳仍以 UTC instant 保存/传输，只有业务日期边界按北京时间计算。
如需调整执行时间，可通过 `systemctl edit pennypilot-settlement.timer` 覆盖 `OnCalendar`（列表项需先清空，避免保留默认时间）：

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 01:00:00 Asia/Shanghai
```

然后执行 `systemctl daemon-reload && systemctl restart pennypilot-settlement.timer`。

手动创建并校验一份备份（脚本会自动使用 `/etc/pennypilot/compose.env`）。备份为
PostgreSQL custom format，生成后会自动做 `pg_restore` 检查并写入 SHA-256 sidecar：

```bash
PENNYPILOT_BACKUP_DIR=/var/backups/pennypilot scripts/backup_postgres.sh
scripts/check_postgres_backup.sh /var/backups/pennypilot/<备份文件>.dump
```

恢复会覆盖备份中包含的数据库对象，必须显式确认；脚本默认会先生成当前数据库的安全备份：

```bash
scripts/restore_postgres.sh /var/backups/pennypilot/<备份文件>.dump --confirm
```

请定期将 `/var/backups/pennypilot` 复制到另一台主机或对象存储，并演练恢复流程；本机备份不能抵御磁盘损坏或主机故障。

## 第二阶段 API

- `POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`
- `GET/POST /api/categories`、`PATCH/DELETE /api/categories/{id}`
- `GET/POST /api/payment-methods`、`PATCH/DELETE /api/payment-methods/{id}`
- `GET/POST /api/transactions`、`GET/PATCH /api/transactions/{id}`
- `POST /api/transactions/{id}/void`

金额字段统一使用整数分（`amount_cents`）；交易通过作废接口保留审计记录，不做物理删除。启用支付方式余额跟踪后，新增、修改和作废交易会在同一数据库事务内联动余额。

## 往来账户与 AI API

往来账户接口为 `GET/POST /api/partners`、`GET/PATCH/DELETE /api/partners/{id}`，流水使用
`GET/POST /api/partners/{id}/ledger`，支持 `prepaid_in`、`prepaid_out`、`credit_use`、
`credit_repay`、`limit_adjust`、`refund` 六类变动。流水包含三组余额的 before/after 快照，
历史记录只通过冲销接口修正；关联收支记录作废时会在同一事务中自动生成补偿流水。

AI 配置使用 `GET/PUT (或 PATCH) /api/ai/config`，API Key 以 Fernet 密文保存且不会在响应中返回。
`POST /api/ai/parse` 只生成解析草稿，`POST /api/ai/confirm` 要求请求体中的 `confirm: true`，
并在字段校验通过后才写入交易；可选的往来流水也会与交易原子提交。一句话里包含多笔记录时（例如一连串消费，
或还款时用了还款券），解析结果的 `records` 会按顺序列出每一笔草稿（`parsed` 为第一笔），前端逐笔勾选后调用
`POST /api/ai/confirm-batch`（`confirm: true` + `drafts`，最多 10 笔）在同一事务中写入，任何一笔校验失败则全部不入账；
批量确认只支持现金收支和转账，往来未结算余额仍需单笔确认。

报告某个资金账户的实际余额（“支付宝现在余额 2345.67”“信用卡目前欠款 3000”）会解析成 `kind=balance_check` 的余额校准草稿，
带 `account_balance_cents` 以及后端算出的 `account_balance_expected_cents` / `account_balance_delta_cents`；确认时后端锁定账户行重新计算差额，
生成一笔收入或支出流水（分类默认“其他收入 / 其他支出”，备注写明系统余额和实际余额），负债账户的欠款增加记为支出。余额一致时拒绝确认。

主通道和备用通道各有一个接口格式（`api_format` / `fallback_api_format`，也可用环境变量 `PENNYPILOT_AI_API_FORMAT`、`PENNYPILOT_AI_FALLBACK_API_FORMAT` 设默认值），在设置页三选一：

| 格式 | 请求路径 | 说明 |
|---|---|---|
| `openai`（默认） | `/v1/chat/completions` | OpenAI 兼容接口；按模型名选择结构化输出和推理参数 |
| `anthropic` | `/v1/messages` | 通过官方 `anthropic` SDK 调用；请求自适应思考（摘要可见、`effort=low`）和结构化输出，被拒绝时退回普通请求 |
| `gemini` | `/v1beta/models/{模型}:streamGenerateContent` | 请求思考摘要和 `responseJsonSchema`（枚举中不含 `null`），被拒绝时退回普通请求 |

接口地址只需填到主机（末尾带 `/v1` 也可以），后端会按格式拼接路径；三种格式都以流式方式调用，思考内容会显示在 AI 记账页的思考面板里。

注册是开放的，所以服务器环境变量里的 AI 接口（地址、模型、Key）默认不对用户开放：`PENNYPILOT_AI_SHARE_WITH_USERS=false`（生产 Compose 的默认值）时，
没有自行配置的用户看不到也用不了服务器的接口，AI 功能会提示先完成配置；只填了 Key 没填地址的用户使用公共默认地址 `https://api.openai.com`。
单人自用或本地开发可以设为 `true`，让所有用户共用服务器配置的接口。

`POST /api/ai/parse-stream` 与 `/api/ai/parse` 的请求体相同，但以 SSE（`text/event-stream`）返回解析过程：
`provider`（开始使用主/备用通道）、`reasoning`（模型的思考摘要增量）、`content`（草稿 JSON 增量）、`status`（复核、切换通道等），
最后一条一定是 `result`（与 `/parse` 相同的解析结果）或 `error`。解析请求对模型使用流式输出，读取超时只限制相邻两段输出的间隔（30 秒），
单次请求总时长上限 90 秒；`gpt-6` 系列使用 `reasoning_effort=low`（该系列无法关闭推理）。无可用模型或模型响应不符合
严格 schema 时，接口会返回带 warning 的本地规则草稿，不会自动入账。`POST /api/ai/analyze` 生成
日/周/月/年/全部/自定义周期报告，`GET /api/ai/reports` 和 `/api/ai/reports/{id}` 用于历史回看。

`GET /api/ai/summary?period=month|year|all|day|week|custom` 返回按北京日期聚合的收支数据（总额、分类、
每日/每月桶、上一周期对比、大额交易），财务分析页的本月图表直接使用该接口，不会调用模型。
`POST /api/ai/ask` 是收支记录页提问栏使用的工具型账本助手（SSE）：模型拿到四个只读工具——`summarize_period`（周期汇总，可按账户/分类/往来/方向限定）、
`list_transactions`（按日期、关键词、金额区间查明细，最多 100 条）、`list_accounts`（账户余额）、`list_partners`（往来未结算余额）——自行决定调用哪些，
每次调用以 `tool`/`tool_result` 事件推送给前端显示，最多 6 轮，最后以 `result` 事件返回答案（报告会保存并带 `report_id`，
归档周期取模型第一次汇总所用的时间段）。提示词只包含三部分：当前北京时间、工具调用方法（含账户/分类/往来单位的 id 对照表）和约束；
页面筛选不会随问题发送，模型自行决定查询范围；“生成报告”按钮会把当前筛选写成明确的问题（如“生成 2026-10-01 至 2026-10-03 的收支报告，只看 支付宝 账户”）。

改账也走这个助手：`propose_update` / `propose_void` / `propose_create` 三个工具只生成方案（修改前后的对照、原因），随 `result` 事件的 `proposals` 返回，
前端以卡片展示，用户点“确认执行”后才通过普通的流水接口（`PATCH /api/transactions/{id}`、`POST /api/transactions/{id}/void`、`POST /api/transactions`）写入，
方案状态（已执行 / 已忽略 / 失败）记录在对话消息里（`POST /api/ai/conversations/{cid}/messages/{mid}/proposals/{index}`）。

问答按对话保存：`/api/ai/ask` 接受 `conversation_id`（省略则新建，返回值带 `conversation_id` 和 `message_id`），上下文从服务端已保存的消息中取最近 12 条；
`GET /api/ai/conversations` 列出历史对话，`GET /api/ai/conversations/{id}` 返回全部消息（含工具步骤和方案），`DELETE` 删除整段对话。前端用 localStorage 记住当前对话，刷新后自动恢复。
三种接口格式各自用原生的函数调用协议（OpenAI `tools`、Anthropic `tool_use`、Gemini `functionDeclarations`），模型调用均为最高推理强度；
没有通道可用时退回本地汇总文本。请求体与 `/api/ai/chat` 相同。

`POST /api/ai/chat` 是不带工具的账本问答（保留给旧客户端）：请求体带 `intent`（`query` 或 `report`）和当前筛选
（`period`/`start_date`/`end_date`、`payment_method_id`、`category_id`、`partner_id`、`direction`），汇总数据只统计筛选范围内的流水，
响应的 `scope` 给出范围名称；“生成报告”会把报告保存到分析历史（`report_id`）。未传 `intent` 时仍用本地规则判断，记账句子返回
`intent=bookkeeping`。模型只接收聚合数字，未配置模型时用本地文本回答。问答和报告以最高推理强度调用模型
（OpenAI 格式 `reasoning_effort=high`、DeepSeek 开启思考、Anthropic `effort=max`、Gemini `thinkingLevel=high`），记账解析保持低强度。
AI 记账页只做记账：`/api/ai/parse-stream` 会先推送一个 `intent` 事件，前端据此在对话里提示“查账请到收支记录页”。

每日结算接口为 `GET /api/settlements`（支持 `start_date`、`end_date` 和分页）、
`GET /api/settlements/{YYYY-MM-DD}`、`POST /api/settlements/run` 和
`POST /api/settlements/recalculate`。普通生成不会覆盖已有快照；重算请求从指定日期更新已有快照并保留
`is_recalculated`/`recalculated_at` 审计标记，同时补齐请求范围内缺失的日期（单次最多 3660 天）。快照中的往来余额按流水发生时间（UTC instant）重放，但日期边界采用北京时间，支持历史补录和冲销。

所有新增迁移由容器启动时执行 `alembic upgrade head`，当前 head 为 `20260819_0010_feedback`。

## 停止与清理

```bash
docker compose down             # 停止容器，保留数据卷
docker compose down -v          # 同时删除 PostgreSQL 数据（谨慎）
```

生产环境请使用强随机密码、独立密钥，并通过反向代理/TLS 暴露服务；不要提交 `.env`。
