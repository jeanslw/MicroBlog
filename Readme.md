# 博客系统部署文档 

版本：v1.0
概述: 本博客基于Flask框架3.1，功能包括：评论点赞、文章分类、banner轮播，带code makedown编辑器等，全部本地加载，支持sqllite和mysql数据库。

## 1. 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.9+ (推荐 3.11) | 运行环境 |
| MySQL | 5.7+ / 8.0+（可选） | 生产环境数据库，开发/测试可用 SQLite 替代 |
| pip | 最新版 | Python 包管理 |

> **SQLite 模式**：无需安装任何数据库，开箱即用，适合开发测试和小型部署。

## 2. 项目结构

```
flaskProject/
├── run.py                         # 开发入口
├── wsgi.py                        # WSGI 部署入口
├── uwsgi.ini                      # uWSGI 配置文件
├── config.py                      # 配置文件（密钥 / 数据库类型 / 调试）
├── requirements.txt               # Python 依赖列表
├── data/                          # SQLite 数据库文件目录（自动创建）
├── app/
│   ├── __init__.py                # Flask 工厂 + 错误处理 + 全局上下文
│   ├── db.py                      # 统一数据库层（自动切换 MySQL / SQLite）
│   ├── extensions.py              # 共享数据库查询
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

`requirements.txt` 内容：

```
Flask==3.1.3
PyMySQL==1.2.0
blinker==1.9.0
click==8.4.2
colorama==0.4.6
itsdangerous==2.2.0
Jinja2==3.1.6
MarkupSafe==3.0.3
Werkzeug==3.1.8
```

### 4.3 配置数据库

编辑 `config.py`，选择数据库类型：

```python
SECRET_KEY = "blog_2026_secure_key_xyz123"  # 生产环境请改为复杂随机字符串
DEBUG = False                                # 生产环境改为 False

# 数据库类型: "mysql" 或 "sqlite"
DB_TYPE = "sqlite"

# MySQL 配置（DB_TYPE = "mysql" 时生效）
MYSQL_HOST = "localhost"
MYSQL_USER = "root"
MYSQL_PWD = "your_password"                  # 数据库密码（改）
MYSQL_DB = "flask_blog"

# SQLite 配置（DB_TYPE = "sqlite" 时生效）
SQLITE_PATH = "data/blog.db"

PAGE_SIZE = 6                                # 每页文章数
```

#### 方式一：SQLite（推荐开发/测试）

无需额外配置，改 `DB_TYPE = "sqlite"` 即可。首次启动自动在 `data/` 目录创建数据库并建表，默认管理员 `admin` / `123456`。

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

如果 MySQL 没有使用自动导入脚本，手动执行以下 SQL：

```sql
-- 管理员表
CREATE TABLE admin (
    id INT NOT NULL AUTO_INCREMENT,
    username VARCHAR(50) NOT NULL,
    password VARCHAR(100) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 文章表
CREATE TABLE article (
    id INT NOT NULL AUTO_INCREMENT,
    title VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'draft',
    create_time VARCHAR(50) DEFAULT NULL,
    update_time VARCHAR(50) DEFAULT NULL,
    vote_num INT DEFAULT 0,
    category_id INT DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 栏目分类表
CREATE TABLE category (
    id INT NOT NULL AUTO_INCREMENT,
    cat_name VARCHAR(60) NOT NULL,
    tag_text VARCHAR(60) DEFAULT '',
    create_time VARCHAR(50) DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY (cat_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 评论表
CREATE TABLE comment (
    id INT NOT NULL AUTO_INCREMENT,
    article_id INT DEFAULT NULL,
    username VARCHAR(100) DEFAULT '游客',
    content TEXT NOT NULL,
    create_time VARCHAR(50) DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 回复表
CREATE TABLE reply (
    id INT NOT NULL AUTO_INCREMENT,
    comment_id INT DEFAULT NULL,
    username VARCHAR(100) DEFAULT '游客',
    content TEXT NOT NULL,
    create_time VARCHAR(50) DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 轮播图表
CREATE TABLE banner (
    id INT NOT NULL AUTO_INCREMENT,
    img_path VARCHAR(200) NOT NULL,
    link_url VARCHAR(500) DEFAULT '',
    title VARCHAR(100) DEFAULT '',
    desc_text VARCHAR(200) DEFAULT '',
    sort INT DEFAULT 0,
    create_time VARCHAR(50) DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 站点配置表
CREATE TABLE site_config (
    id INT NOT NULL AUTO_INCREMENT,
    site_name VARCHAR(100) NOT NULL DEFAULT '我的博客',
    favicon_path VARCHAR(200) DEFAULT 'static/favicon.ico',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 点赞记录表（可选，防刷）
CREATE TABLE vote_log (
    id INT NOT NULL AUTO_INCREMENT,
    article_id INT DEFAULT NULL,
    ip VARCHAR(100) DEFAULT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 初始化数据
INSERT INTO site_config (site_name) VALUES ('我的博客');
INSERT INTO admin (username, password) VALUES ('admin', '123456');
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

## 5. 首次登录

- 访问 `http://your-server/admin/login`
- 默认账号：`admin`
- 默认密码：`123456`
- **登录后立即修改密码**：管理 → 改密码

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


## 8. 如有建议可在 GitHub 仓库提 issue ，或联系EMAIL:jeanslw@qq.com