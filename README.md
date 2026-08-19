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
并在字段校验通过后才写入交易；可选的往来流水也会与交易原子提交。无可用模型或模型响应不符合
严格 schema 时，接口会返回带 warning 的本地规则草稿，不会自动入账。`POST /api/ai/analyze` 生成
日/周/月/自定义周期报告，`GET /api/ai/reports` 和 `/api/ai/reports/{id}` 用于历史回看。

每日结算接口为 `GET /api/settlements`（支持 `start_date`、`end_date` 和分页）、
`GET /api/settlements/{YYYY-MM-DD}`、`POST /api/settlements/run` 和
`POST /api/settlements/recalculate`。普通生成不会覆盖已有快照；重算请求从指定日期更新已有快照并保留
`is_recalculated`/`recalculated_at` 审计标记，同时补齐请求范围内缺失的日期（单次最多 3660 天）。快照中的往来余额按流水发生时间（UTC instant）重放，但日期边界采用北京时间，支持历史补录和冲销。

所有新增迁移由容器启动时执行 `alembic upgrade head`，当前 head 为 `20260805_0006_partner_website`。

## 停止与清理

```bash
docker compose down             # 停止容器，保留数据卷
docker compose down -v          # 同时删除 PostgreSQL 数据（谨慎）
```

生产环境请使用强随机密码、独立密钥，并通过反向代理/TLS 暴露服务；不要提交 `.env`。
