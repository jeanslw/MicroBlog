-- ============================================================
-- Flask 博客系统 MySQL 建表脚本
-- 兼容 MySQL 5.7+ / 8.0+，已通过 STRICT_TRANS_TABLES 严格模式校验
--
-- 使用方法：
--   mysql -uroot -p flask_blog < MySQL/init.sql
--   或 Docker 容器首次启动自动执行（挂载到 /docker-entrypoint-initdb.d/）
--
-- 注意：本脚本不创建初始管理员账号（避免明文密码入库）
--   请在启动后通过 docker exec 或应用界面设置，参考 Readme 4.7.5 节
-- ============================================================

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

-- 不强制设置 SQL_MODE，使用服务端默认（推荐生产保持 STRICT_TRANS_TABLES）
-- 若需显式启用严格模式，取消下行注释：
-- SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';


-- --------------------------------------------------------
-- 数据库
-- --------------------------------------------------------
CREATE DATABASE IF NOT EXISTS `flask_blog`
    /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci */;
USE `flask_blog`;


-- --------------------------------------------------------
-- 表：admin（管理员）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `admin`;
CREATE TABLE `admin` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(50) NOT NULL,
  -- Werkzeug 3.x pbkdf2:sha256:600000 哈希约 102 字符；预留 256 兼容未来 scrypt/argon2
  `password` varchar(255) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：article（文章）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `article`;
CREATE TABLE `article` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` varchar(500) NOT NULL,
  `content` mediumtext NOT NULL,
  `status` varchar(20) DEFAULT 'draft',
  `create_time` varchar(50) DEFAULT NULL,
  `update_time` varchar(50) DEFAULT NULL,
  `vote_num` int DEFAULT '0',
  `category_id` int DEFAULT NULL COMMENT '所属栏目',
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`),
  KEY `idx_category_id` (`category_id`),
  KEY `idx_create_time` (`create_time`),
  KEY `idx_status_cat_time` (`status`, `category_id`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：category（栏目分类）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `category`;
CREATE TABLE `category` (
  `id` int NOT NULL AUTO_INCREMENT,
  `cat_name` varchar(60) NOT NULL COMMENT '栏目名称',
  `tag_text` varchar(60) DEFAULT '' COMMENT '标签',
  `create_time` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_cat_name` (`cat_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：comment（评论）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `comment`;
CREATE TABLE `comment` (
  `id` int NOT NULL AUTO_INCREMENT,
  `article_id` int DEFAULT NULL,
  `username` varchar(50) DEFAULT '游客',
  `content` text NOT NULL,
  `create_time` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_article_id` (`article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：reply（回复）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `reply`;
CREATE TABLE `reply` (
  `id` int NOT NULL AUTO_INCREMENT,
  `comment_id` int DEFAULT NULL,
  `username` varchar(50) DEFAULT '游客',
  `content` text NOT NULL,
  `create_time` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_comment_id` (`comment_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：banner（轮播图）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `banner`;
CREATE TABLE `banner` (
  `id` int NOT NULL AUTO_INCREMENT,
  -- UUID + secure_filename 后路径可能较长，扩到 500 防截断
  `img_path` varchar(500) NOT NULL COMMENT '图片存储路径',
  `link_url` varchar(500) DEFAULT '' COMMENT '跳转链接',
  `title` varchar(100) DEFAULT '' COMMENT '轮播标题',
  `desc_text` varchar(200) DEFAULT '' COMMENT '轮播描述',
  `sort` int DEFAULT '0' COMMENT '排序数字，越大越靠前',
  `create_time` varchar(50) DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1' COMMENT '是否在首页展示：1展示 0已撤回（下架）',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：site_config（站点配置）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `site_config`;
CREATE TABLE `site_config` (
  `id` int NOT NULL AUTO_INCREMENT,
  `site_name` varchar(100) NOT NULL DEFAULT '我的博客',
  `favicon_path` varchar(200) DEFAULT 'static/favicon.ico',
  `logo_path` varchar(200) DEFAULT '' COMMENT '网站 Logo 图片 URL（导航栏显示，上传时过大自动缩放）',
  `bg_style` varchar(50) DEFAULT 'bg1' COMMENT '背景风格：bg1~bg10/vdysjx/bg13 内置图库或 custom 自定义',
  `bg_custom` varchar(500) DEFAULT '' COMMENT '自定义背景图片 URL（bg_style=custom 时生效）',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：vote_log（点赞记录，防刷）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `vote_log`;
CREATE TABLE `vote_log` (
  `id` int NOT NULL AUTO_INCREMENT,
  `article_id` int DEFAULT NULL,
  `ip` varchar(100) DEFAULT NULL,
  `create_time` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_article_ip` (`article_id`, `ip`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 表：login_attempt（登录失败计数，防爆破）
-- --------------------------------------------------------
DROP TABLE IF EXISTS `login_attempt`;
CREATE TABLE `login_attempt` (
  `id` int NOT NULL AUTO_INCREMENT,
  `ip` varchar(100) NOT NULL,
  `username` varchar(100) NOT NULL,
  `fail_count` int NOT NULL DEFAULT '0',
  `lock_until` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ip_username` (`ip`, `username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- --------------------------------------------------------
-- 初始化数据
-- --------------------------------------------------------
-- 站点配置（仅一条）
INSERT INTO `site_config` (`id`, `site_name`, `favicon_path`, `logo_path`, `bg_style`, `bg_custom`)
VALUES (1, '我的博客', 'static/favicon.ico', '', 'bg1', '');

-- ⚠️ 不在此插入初始管理员账号（避免明文密码）
-- 请用以下任一方式创建管理员：
--
-- 方式 A：用 Python 生成哈希后 INSERT
--   docker exec -it flask-blog-web python -c "from werkzeug.security import generate_password_hash as g; print(g('你的密码'))"
--   mysql -uroot -p flask_blog -e "INSERT INTO admin (username, password) VALUES ('admin', '<上面输出的哈希>')"
--
-- 方式 B：用 SQLite 模式首次启动（设 BLOG_INIT_ADMIN_PWD），数据库自动建管理员后导出再导入 MySQL
--
-- 方式 C（仅测试）：临时用明文哈希占位（登录会失败，仅占行）
--   INSERT INTO admin (username, password) VALUES ('admin', 'must_replace_me');


/*!40103 SET TIME_ZONE=IFNULL(@OLD_TIME_ZONE, 'system') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IFNULL(@OLD_FOREIGN_KEY_CHECKS, 1) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40111 SET SQL_NOTES=IFNULL(@OLD_SQL_NOTES, 1) */;
