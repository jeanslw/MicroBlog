# 博客系统部署文档

版本：v1.0
概述: 本博客基于Flask框架3.1，功能包括：评论点赞、文章分类、banner轮播，带code makedown编辑器等，全部本地加载，支持sqllite和mysql数据库。

## 1. 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.9+ (推荐 3.11) | 运行环境 |
| MySQL | 5.7+ / 8.0+（可选） | 生产环境数据库，开发/测试可用 SQLite 替代 |
| pip | 最新版 | Python 包管理 |
| Docker | 20.10+（可选） | 容器化部署，免去环境配置 |
| Docker Compose | v2+（可选） | 多容器编排 |

> **SQLite 模式**：无需安装任何数据库，开箱即用，适合开发测试和小型部署。
> **Docker 模式**：见 4.7 节，一条命令启动 web + db + nginx。

## 2. 项目结构

```
flaskProject/
├── run.py                         # 开发入口
├── wsgi.py                        # WSGI 部署入口
├── uwsgi.ini                      # uWSGI 配置文件（Linux 裸机部署）
├── Dockerfile                     # Docker 镜像构建
├── docker-compose.yml             # 多容器编排（web + db + nginx）
├── .dockerignore                  # Docker 构建忽略
├── .env.example                   # Flask 应用环境变量模板（裸机）
├── .env.docker.example            # Docker Compose 变量模板
├── config.py                      # 配置文件（密钥 / 数据库类型 / 调试）
├── requirements.txt               # Python 依赖列表
├── data/                          # SQLite 数据库文件目录（自动创建）
├── nginx/
│   └── nginx.conf                 # Nginx 反代配置（Docker 用）
├── MySQL/
│   └── init.sql                   # MySQL 建表脚本
├── app/
│   ├── __init__.py                # Flask 工厂 + 错误处理 + 全局上下文
│   ├── db.py                      # 统一数据库层（自动切换 MySQL / SQLite）
│   ├── extensions.py              # 共享数据库查询 + 防爆破
│   ├── blog/                      # 博客模块
│   ├── admin/                     # 管理员模块
│   ├── banner/                    # 轮播图模块
│   └── comment/                   # 评论点赞模块
├── templates/                     # Jinja2 模板
│   ├── base.html                  # 公共布局
│   ├── blog/                      # 博客页面
│   ├── admin/                     # 管理页面
│   └── banner/                    # 轮播管理
└── static/
    ├── favicon.ico
    ├── banner/                    # 上传的轮播图
    └── lib/                       # 本地第三方库（无需外网）
```

## 3. 本地静态资源说明

所有 JS/CSS 均已本地化，存放在 `static/lib/` 目录，**部署后无需访问任何 CDN**，内网完全可用。

| 文件 | 大小 | 用途 |
|------|------|------|
| `bootstrap.min.css` | 228 KB | Bootstrap 5.3 样式框架 |
| `bootstrap.bundle.min.js` | 79 KB | Bootstrap JS（导航/折叠/轮播） |
| `bootstrap-icons.css` | 94 KB | Bootstrap 图标库 |
| `easymde.min.js` | 320 KB | Markdown 富文本编辑器 |
| `easymde.min.css` | 13 KB | 编辑器样式 |
| `marked.min.js` | 39 KB | Markdown → HTML 转换 |
| `prism.min.js` | 19 KB | 代码语法高亮 |
| `prism-tomorrow.min.css` | 6 KB | 代码暗色主题 |
| `prism-autoloader.min.js` | 6 KB | 按需加载编程语言高亮 |

> 页面中所有 `<link>` 和 `<script>` 均使用 `url_for('static', ...)` 引用本地文件，零外链。

## 4. 部署步骤

### 4.1 获取代码

```bash
# 将项目目录复制到服务器
scp -r flaskProject/ user@server:/opt/
cd /opt/flaskProject
```

### 4.2 安装 Python 依赖

```bash
# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# 安装依赖
pip install -r requirements.txt
```

`requirements.txt` 内容（仅列出直接依赖，其余由 pip 自动解析）：

| 依赖 | 版本 | 用途 |
|------|------|------|
| Flask | 3.1.3 | Web 框架 |
| PyMySQL | 1.2.0 | MySQL 驱动 |
| gunicorn | 23.0.0 | WSGI 服务器（Docker / Linux 生产） |
| python-dotenv | 1.2.1 | 从 `.env` 文件读取环境变量（可选，未安装不影响运行） |

> uWSGI 用户可额外 `pip install uwsgi`，配置文件已提供 [uwsgi.ini](uwsgi.ini)。

### 4.3 配置（通过环境变量）

所有配置通过环境变量注入，**`config.py` 不必修改**。常见变量：

| 变量名 | 默认 | 说明 |
|--------|------|------|
| `BLOG_SECRET_KEY` | （无） | Session/CSRF 密钥；**生产必须设置**，否则启动报错 |
| `BLOG_ENV` | （无） | 设为 `production` 时启用 Secure Cookie 并强制校验 SECRET_KEY |
| `BLOG_DEBUG` | `False` | 调试模式（生产保持 False，避免 Werkzeug 调试器暴露） |
| `BLOG_DB_TYPE` | `sqlite` | `sqlite` 或 `mysql` |
| `BLOG_MYSQL_HOST` / `BLOG_MYSQL_USER` / `BLOG_MYSQL_PWD` / `BLOG_MYSQL_DB` | - | MySQL 连接信息 |
| `BLOG_SQLITE_PATH` | `data/blog.db` | SQLite 文件路径 |
| `BLOG_PAGE_SIZE` | `6` | 每页文章数 |
| `BLOG_STATIC_MAX_AGE` | `0` | 静态文件缓存秒数 |
| `BLOG_INIT_ADMIN_USER` | `admin` | SQLite 首次建表时创建的管理员账号 |
| `BLOG_INIT_ADMIN_PWD` | （无） | SQLite 首次建表时创建的管理员密码，**未设置则不创建初始管理员** |

Linux 示例：

```bash
export BLOG_ENV=production
export BLOG_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export BLOG_DB_TYPE=sqlite
export BLOG_INIT_ADMIN_USER=admin
export BLOG_INIT_ADMIN_PWD='你的强密码'
```

Windows PowerShell 示例：

```powershell
$env:BLOG_ENV = "production"
$env:BLOG_SECRET_KEY = -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | % {[char]$_})
$env:BLOG_DB_TYPE = "sqlite"
$env:BLOG_INIT_ADMIN_PWD = "你的强密码"
```

#### 方式一：SQLite（推荐开发/测试）

无需额外配置，设置 `BLOG_DB_TYPE=sqlite` 并设置 `BLOG_INIT_ADMIN_PWD`，首次启动自动在 `data/` 目录建表并创建管理员。

#### 方式二：MySQL（推荐生产环境）

1. 安装 MySQL：

```bash
# Ubuntu/Debian
sudo apt install mysql-server

# CentOS/RHEL
sudo yum install mysql-server
```

2. 创建数据库：

```sql
CREATE DATABASE flask_blog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

3. 改 `config.py`：`DB_TYPE = "mysql"`，填入正确的数据库账号密码。

4. 建表并写入初始数据（参考下方 4.4 节 SQL 脚本），或直接用下面的命令导入：

```bash
mysql -u root -p flask_blog < MySQL/init.sql
```

### 4.4 手动建表 SQL（MySQL 用户参考）

如果 MySQL 没有使用自动导入脚本，**直接使用 [`MySQL/init.sql`](MySQL/init.sql) 即可**（已通过 STRICT_TRANS_TABLES 严格模式校验，已含索引、字符集、字段长度适配）：

```bash
mysql -uroot -p < MySQL/init.sql
```

> ⚠️ **生产环境推荐启用 MySQL 严格模式**（默认已启用），避免数据被静默截断：
> ```sql
> -- 查看当前 sql_mode
> SELECT @@sql_mode;
> -- 推荐配置（my.cnf / my.ini）
> [mysqld]
> sql_mode = STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION
> ```

**关键字段长度说明**（已在 init.sql 中正确设置，手动建表时切勿缩小）：

| 字段 | 长度 | 原因 |
|------|------|------|
| `admin.password` | VARCHAR(255) | Werkzeug 3.x pbkdf2:sha256:600000 哈希约 102 字符，预留 256 兼容未来 scrypt/argon2 |
| `banner.img_path` | VARCHAR(500) | 上传路径含 UUID + secure_filename，可能较长 |
| `article.content` | MEDIUMTEXT | 文章正文可能较长，TEXT 仅 64KB，MEDIUMTEXT 16MB |
| `article.title` | VARCHAR(500) | 长标题兼容 |

**初始化管理员账号**（init.sql 不含明文密码 INSERT，需手动）：

```bash
# 1. 生成密码哈希
python -c "from werkzeug.security import generate_password_hash as g; print(g('你的强密码'))"
# 或 Docker 环境：
# docker exec -it flask-blog-web python -c "from werkzeug.security import generate_password_hash as g; print(g('你的强密码'))"

# 2. INSERT 到数据库
mysql -uroot -p flask_blog -e "INSERT INTO admin (username, password) VALUES ('admin', '<上一步输出的哈希>')"
```

### 4.5 启动服务

**开发/测试用：**

```bash
python run.py
# 监听 http://127.0.0.1:5000
```

**生产部署推荐方案：**

```bash
# 方案一：uWSGI（Linux）
pip install uwsgi
uwsgi --ini uwsgi.ini

# 方案二：gunicorn（Linux）
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 wsgi:application

# 方案三：waitress（跨平台，Windows 可用）
pip install waitress
waitress-serve --port=5000 wsgi:application
```

**Nginx 反向代理（可选）：**

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 10m;  # 允许上传轮播图

    location /static {
        alias /opt/flaskProject/static;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 4.6 安装字体（可选）

若页面代码块未使用等宽字体，可安装 Fira Code：

```bash
# Ubuntu
sudo apt install fonts-firacode
# 或手动下载放到系统字体目录
```

### 4.7 Docker Compose 部署（推荐生产）

适合不希望手动配置 Python/MySQL/Nginx 的用户，一条命令拉起全套服务。

#### 4.7.0 服务器准备（首次部署必做）

```bash
# 1. 安装 Docker + Compose 插件（已安装可跳过）
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # 免 sudo，需重新登录生效

# 2. 拉取项目代码
git clone <你的仓库地址> /opt/flaskProject
cd /opt/flaskProject

# 3. 确认 Docker 可用
docker --version               # 期望 20.10+
docker compose version         # 期望 v2+
```

#### 4.7.1 准备变量文件

```bash
cp .env.docker.example .env.docker
vim .env.docker
```

`.env.docker` 关键变量（**必填**）：

| 变量 | 说明 | 示例 |
|------|------|------|
| `BLOG_SECRET_KEY` | Flask Session/CSRF 密钥 | `python -c "import secrets;print(secrets.token_hex(32))"` 生成 |
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码 | 强密码 |
| `MYSQL_PASSWORD` | MySQL 业务账号密码 | 强密码 |
| `BLOG_DB_TYPE` | 数据库类型 | `mysql` 或 `sqlite` |
| `BLOG_INIT_ADMIN_PWD` | 初始管理员密码（仅 SQLite 首次建表） | 强密码 |

#### 4.7.2 启动方式

**A. 完整模式（web + db + nginx，推荐生产）**

```bash
docker compose --env-file .env.docker --profile full up -d
```

- 访问：`http://localhost`（nginx 反代，80 端口）
- 直连 Flask：`http://localhost:5000`

**B. 仅 web + db（无 nginx，适合内部/调试）**

```bash
docker compose --env-file .env.docker --profile mysql up -d
```

- 访问：`http://localhost:5000`

**C. 仅 web（SQLite 单容器，最简）**

```bash
# 修改 .env.docker 中 BLOG_DB_TYPE=sqlite
docker compose --env-file .env.docker up -d web --no-deps
```

#### 4.7.2.1 验证部署成功

启动后用以下命令确认服务正常：

```bash
# 1. 容器状态（期望三个 Up，web/db 显示 (healthy)）
docker compose --env-file .env.docker --profile full ps

# 2. 健康检查
curl -I http://localhost/                 # 经 nginx，期望 200
curl -I http://localhost:5000/            # 直连 Flask，期望 200

# 3. 查看启动日志（无 ERROR 即正常）
docker compose --env-file .env.docker logs web | tail -20
docker compose --env-file .env.docker logs db  | tail -20

# 4. 浏览器访问
# 首页：    http://<服务器IP>/
# 后台登录：http://<服务器IP>/admin/login
```

#### 4.7.3 容器架构

```
┌──────────────────────────────────────────────────┐
│  Host                                            │
│  ┌──────────┐   ┌──────────┐   ┌─────────────┐  │
│  │  nginx   │──▶│   web    │──▶│     db      │  │
│  │  :80     │   │  :5000   │   │  :3306      │  │
│  └──────────┘   └──────────┘   └─────────────┘  │
│       │              │                │          │
│       │              │                ▼          │
│       │              │          ┌──────────┐     │
│       │              │          │  volume  │     │
│       │              │          │ mysql-db │     │
│       │              │          └──────────┘     │
│       │              ▼                            │
│       │         ┌──────────┐                      │
│       │         │ ./data   │ (SQLite 持久化)      │
│       │         │ ./static │ (上传图持久化)        │
│       │         └──────────┘                      │
│       ▼                                            │
│   ./static (静态资源由 nginx 直接提供)             │
└──────────────────────────────────────────────────┘
```

#### 4.7.4 常用运维命令

```bash
# 查看日志
docker compose logs -f web
docker compose logs -f db

# 重启某个服务
docker compose restart web

# 停止并清理（保留卷）
docker compose down

# 停止并删除数据卷（慎用！清空数据库）
docker compose down -v

# 重新构建镜像（代码改动后）
docker compose build web
docker compose --env-file .env.docker --profile full up -d
```

#### 4.7.5 首次初始化 MySQL

- 容器首次启动会自动执行 `MySQL/init.sql` 建表（含严格模式校验、字符集、索引）
- 管理员账号**自动创建**：在 `.env.docker` 中设置 `BLOG_INIT_ADMIN_PWD`，首次启动时 Web 容器会自动创建 `admin` 账号
- 若需修改管理员用户名，设置 `BLOG_INIT_ADMIN_USER`（默认 `admin`）

```bash
# 验证管理员已创建
docker exec -i flask-blog-db mysql -uroot -p<ROOT密码> flask_blog -e \
  "SELECT id, username FROM admin;"
```

> 若未设置 `BLOG_INIT_ADMIN_PWD`，管理员不会创建。补设后重启 Web 容器即可自动补建：
> ```bash
> docker compose restart web
> ```

#### 4.7.6 升级镜像

```bash
git pull
docker compose build web
docker compose --env-file .env.docker --profile full up -d
```

#### 4.7.7 反代域名与 HTTPS

修改 `nginx/nginx.conf` 中 `server_name _;` 为你的域名，挂载证书后改 443 监听即可，例如：

```nginx
server {
    listen 443 ssl http2;
    server_name blog.example.com;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    # ... 其余配置同 nginx.conf
}
```

挂载证书：在 `docker-compose.yml` 的 nginx 服务 `volumes` 加：
```yaml
- /etc/letsencrypt:/etc/nginx/certs:ro
```

#### 4.7.8 防火墙与端口

生产环境**仅开放 80/443**，不要把 5000（Flask）和 3306（MySQL）暴露到公网：

```bash
# Ubuntu UFW 示例
sudo ufw allow 22/tcp       # SSH
sudo ufw allow 80/tcp       # HTTP
sudo ufw allow 443/tcp      # HTTPS
sudo ufw deny 5000/tcp      # Flask 直连（仅容器内部用）
sudo ufw deny 3306/tcp      # MySQL（仅容器内部用）
sudo ufw enable
```

若无需从宿主机连数据库调试，建议把 `docker-compose.yml` 中 `db` 服务的 `ports: - "3306:3306"` 注释掉，彻底不暴露。

#### 4.7.9 首次部署检查清单

部署完成后逐项确认：

| 检查项 | 命令 | 期望结果 |
|--------|------|----------|
| 容器状态 | `docker compose --env-file .env.docker --profile full ps` | 3 个 `Up`，web/db 显示 `(healthy)` |
| Web 日志 | `docker compose logs web \| tail -30` | 无 `ERROR`/`Traceback` |
| DB 日志 | `docker compose logs db \| tail -30` | 出现 `ready for connections` |
| 首页访问 | `curl -I http://localhost/` | `HTTP/1.1 200` |
| 后台页面 | `curl -I http://localhost/admin/login` | `HTTP/1.1 200` |
| 管理员账号 | `docker exec -i flask-blog-db mysql -uroot -p<密码> flask_blog -e "SELECT count(*) FROM admin"` | `count(*) >= 1` |
| 静态资源 | `curl -I http://localhost/static/favicon.ico` | `HTTP/1.1 200` |
| 防火墙 | `sudo ufw status` | 5000/3306 为 DENY |

## 5. 首次登录

管理员账号由系统**自动创建**，无需手动 INSERT：

1. 确保 `.env`（或环境变量）中已设置 `BLOG_INIT_ADMIN_PWD`
2. 启动服务后，访问 `http://your-server/admin/login`
3. 用 `admin` / 你设置的密码登录
4. **登录后立即在「改密码」修改为强密码**

> 若未设置 `BLOG_INIT_ADMIN_PWD`，管理员不会创建，启动日志会有警告。补设后重启服务即可自动补建。

## 6. 目录权限

```bash
# 确保上传目录可写
mkdir -p static/banner
chmod 755 static/banner

# SQLite 模式需要 data 目录可写（首次启动自动创建）
mkdir -p data
chmod 755 data
```

## 7. 常见问题

**Q: 页面样式错乱？**
确认 `static/lib/` 下 9 个文件完整存在，见第 3 节列表。

**Q: 数据库连接失败（MySQL）？**
- 确认 MySQL 服务已启动
- 确认 `config.py` 中数据库账号密码正确
- 确认 `DB_TYPE = "mysql"`
- 确认数据库 `flask_blog` 已创建且表结构完整

**Q: 数据库连接失败（SQLite）？**
- 确认 `DB_TYPE = "sqlite"`
- 确认 `data/` 目录存在且可写
- 删除 `data/blog.db` 后重启可重置数据库

**Q: 如何切换数据库？**
修改 `config.py` 中 `DB_TYPE` 即可（`"mysql"` 或 `"sqlite"`），代码自动适配，无需改动业务逻辑。

**Q: 轮播图上传后不显示？**
确认 `static/banner/` 目录存在且可写。

**Q: 编辑器（EasyMDE）加载不出来？**
确认 `static/lib/easymde.min.js` 和 `static/lib/marked.min.js` 存在。

**Q: docker compose 启动报 `must be set in .env.docker`？**
`.env.docker` 没创建或必填变量没填。执行 `cp .env.docker.example .env.docker` 后填入 `BLOG_SECRET_KEY`、`MYSQL_ROOT_PASSWORD`、`MYSQL_PASSWORD`。

**Q: 启动后 80/5000 端口被占？**
修改 `docker-compose.yml` 端口映射，如 `"8080:80"`、`"5001:5000"`，再用新端口访问。

**Q: web 容器一直 restarting？**
`docker compose logs web` 查看原因。常见：DB 还没 healthy 就启动（等 30 秒再重启一次）、`BLOG_SECRET_KEY` 未设置。

**Q: 首次启动很慢？**
MySQL 首次初始化要 30-60 秒，`db` 容器 `healthy` 后 `web` 才会启动，属正常。可用 `docker compose logs -f db` 观察进度。

**Q: 管理员账号登录提示密码错误？**
`admin.password` 字段必须是 `generate_password_hash` 生成的哈希，**明文密码无法登录**。重新生成哈希后 `UPDATE admin SET password='<哈希>' WHERE username='admin'`。

**Q: `docker compose down -v` 后数据全没了？**
`-v` 会删除命名卷（MySQL 数据）。日常停止用 `docker compose down`（不带 `-v`）。

**Q: 改了代码怎么生效？**
`docker compose build web && docker compose --env-file .env.docker --profile full up -d` 重建 web 镜像并滚动重启。


## 8. 如有建议可在 GitHub 仓库提 issue ，或联系EMAIL:jeanslw@qq.com
