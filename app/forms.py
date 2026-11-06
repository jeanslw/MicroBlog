"""Flask-WTF 表单类.

所有写操作通过表单类统一校验,自动附带 CSRF token.
字段名尽量保持与原有 HTML form 字段一致,减少模板改动.
"""

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileSize
from wtforms import (
    BooleanField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)

from app.timeutil import is_valid_timezone


class LoginForm(FlaskForm):
    username = StringField("账号", validators=[DataRequired(), Length(max=50)])
    password = PasswordField("密码", validators=[DataRequired()])
    submit = SubmitField("登录")


class ChangePwdForm(FlaskForm):
    old_pwd = PasswordField("原密码", validators=[DataRequired()])
    new_pwd = PasswordField("新密码", validators=[DataRequired(), Length(min=6, max=128)])
    confirm_pwd = PasswordField("确认新密码", validators=[DataRequired()])

    def validate_confirm_pwd(self, field):
        if field.data != self.new_pwd.data:
            raise ValidationError("两次输入的新密码不一致")


class SetupForm(FlaskForm):
    """首次安装引导:创建管理员账号 + 邮箱 + 密码"""

    username = StringField("账号", validators=[DataRequired(), Length(max=50)])
    email = StringField("邮箱", validators=[Optional(), Email(), Length(max=200)])
    password = PasswordField("密码", validators=[DataRequired(), Length(min=6, max=128)])
    confirm_password = PasswordField("确认密码", validators=[DataRequired()])
    submit = SubmitField("完成安装")

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("两次输入的密码不一致")


class ForgotForm(FlaskForm):
    username = StringField("账号", validators=[DataRequired(), Length(max=50)])
    email = StringField("邮箱", validators=[DataRequired(), Email(), Length(max=200)])
    submit = SubmitField("发送找回邮件")


class ResetForm(FlaskForm):
    new_pwd = PasswordField("新密码", validators=[DataRequired(), Length(min=6, max=128)])
    confirm_pwd = PasswordField("确认新密码", validators=[DataRequired()])
    submit = SubmitField("重置密码")

    def validate_confirm_pwd(self, field):
        if field.data != self.new_pwd.data:
            raise ValidationError("两次输入的新密码不一致")


LOG_LEVEL_CHOICES = [
    ("", "跟随环境变量"),
    ("AUTO", "自动"),
    ("DEBUG", "DEBUG"),
    ("INFO", "INFO"),
    ("WARNING", "WARNING"),
    ("ERROR", "ERROR"),
    ("CRITICAL", "CRITICAL"),
]

LOG_FORMAT_CHOICES = [
    ("", "跟随环境变量"),
    ("auto", "自动"),
    ("json", "JSON"),
    ("text", "文本"),
]


class SystemSettingForm(FlaskForm):
    """系统设置：时区、运行时参数与 SMTP 邮件配置。"""

    timezone = StringField("站点时区", validators=[DataRequired(), Length(max=100)])
    follow_browser_tz = BooleanField("跟随访客浏览器时区")
    page_size = IntegerField("每页条数", validators=[Optional(), NumberRange(min=1, max=100)])
    log_level = SelectField("日志级别", choices=LOG_LEVEL_CHOICES, validators=[Optional()])
    log_format = SelectField("日志格式", choices=LOG_FORMAT_CHOICES, validators=[Optional()])
    slow_request_ms = IntegerField("慢请求阈值(毫秒)", validators=[Optional(), NumberRange(min=0)])
    slow_query_ms = IntegerField("慢 SQL 阈值(毫秒)", validators=[Optional(), NumberRange(min=0)])
    static_max_age = IntegerField("静态资源缓存秒数", validators=[Optional(), NumberRange(min=0)])
    session_lifetime = IntegerField("会话有效期(秒)", validators=[Optional(), NumberRange(min=1)])
    reset_token_max_age = IntegerField("找回令牌有效期(秒)", validators=[Optional(), NumberRange(min=1)])
    auto_schema_migrate = BooleanField("启动时自动迁移数据库")
    allow_schema_ahead = BooleanField("允许数据库版本高于程序版本")
    cookie_secure = BooleanField("仅 HTTPS 下发会话 Cookie")
    mail_host = StringField("SMTP 服务器", validators=[Optional(), Length(max=200)])
    mail_port = IntegerField("端口", validators=[Optional(), NumberRange(min=1, max=65535)], default=587)
    mail_user = StringField("用户名", validators=[Optional(), Length(max=200)])
    mail_password = PasswordField("密码/授权码", validators=[Optional(), Length(max=200)])
    mail_from = StringField("发件人邮箱", validators=[Optional(), Email(), Length(max=200)])
    mail_use_ssl = BooleanField("使用 SSL（465 端口）")
    mail_use_tls = BooleanField("使用 STARTTLS（587 端口）")
    admin_email = StringField("管理员邮箱", validators=[Optional(), Email(), Length(max=200)])
    submit = SubmitField("保存设置")

    def validate_timezone(self, field):
        """校验 IANA 时区名是否有效。"""
        if not is_valid_timezone(field.data):
            raise ValidationError("时区名称无效，请填写 IANA 时区名，如 Asia/Shanghai")


# 内置背景图库(与 static/backgrounds/ 及 themes.css 选择器一一对应)
BG_STYLE_CHOICES = [
    ("bg1", _l("背景 1")),
    ("bg2", _l("背景 2")),
    ("bg3", _l("背景 3")),
    ("bg4", _l("背景 4")),
    ("bg5", _l("背景 5")),
    ("bg6", _l("背景 6")),
    ("bg7", _l("背景 7")),
    ("bg8", _l("背景 8")),
    ("bg9", _l("背景 9")),
    ("bg10", _l("背景 10")),
    ("vdysjx", _l("水墨云山")),
    ("bg13", _l("湖光山色")),
    ("classic", _l("经典")),
    ("custom", _l("自定义图片")),
]


class SiteSettingForm(FlaskForm):
    site_name = StringField("站点名称", validators=[DataRequired(), Length(max=100)])
    bg_style = SelectField("背景风格", choices=BG_STYLE_CHOICES, default="bg1")
    bg_custom = StringField(
        "自定义背景图片 URL",
        validators=[Optional(), Length(max=500)],
        description="bg_style 选“自定义图片”时生效，可填 /static/... 或 http(s)://",
    )
    bg_upload = FileField(
        "上传自定义背景图",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "webp"], "仅支持 jpg/jpeg/png/webp"),
            FileSize(max_size=10 * 1024 * 1024),
        ],
    )
    logo_upload = FileField(
        "上传网站 Logo",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "webp"], "仅支持 jpg/jpeg/png/webp"),
            FileSize(max_size=2 * 1024 * 1024),
        ],
    )
    comments_enabled = BooleanField("开启评论")
    rss_enabled = BooleanField("开启 RSS")
    atom_enabled = BooleanField("开启 Atom")
    sidebar_style = SelectField(
        "栏目分类样式",
        choices=[("book", "书本树形"), ("classic", "经典简洁")],
        default="book",
    )
    submit = SubmitField("保存")


class AboutForm(FlaskForm):
    """'关于我'表单:头像/邮箱/GitHub/个人主页/简介,数据存 about_profile 表"""

    avatar_upload = FileField(
        "上传头像",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "webp"], "仅支持 jpg/jpeg/png/webp"),
            FileSize(max_size=2 * 1024 * 1024),
        ],
    )
    avatar_url = StringField("头像图片 URL", validators=[Optional(), Length(max=500)])
    avatar_clear = BooleanField("清除当前头像")
    about_nickname = StringField("昵称", validators=[Optional(), Length(max=100)])
    about_email = StringField("邮箱", validators=[Optional(), Email(), Length(max=200)])
    about_github = StringField("GitHub 链接", validators=[Optional(), Length(max=200)])
    about_homepage = StringField("个人主页", validators=[Optional(), Length(max=200)])
    about_bio = TextAreaField("个人简介", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("保存")


class CategoryForm(FlaskForm):
    cat_name = StringField("栏目名称", validators=[DataRequired(), Length(max=60)])
    tag_text = StringField("标签", validators=[Optional(), Length(max=60)])
    submit = SubmitField("新增栏目")


class ArticleForm(FlaskForm):
    title = StringField("标题", validators=[DataRequired(), Length(max=500)])
    content = TextAreaField("正文", validators=[DataRequired()])
    status = SelectField("状态", choices=[("draft", "草稿"), ("publish", "发布")], default="draft")
    category_id = SelectField("栏目", coerce=int, validators=[Optional()])
    seo_description = StringField("SEO 描述", validators=[Optional(), Length(max=300)])
    seo_keywords = StringField("SEO 关键词", validators=[Optional(), Length(max=300)])
    submit = SubmitField("保存")


class BannerForm(FlaskForm):
    banner_img = FileField(
        "轮播图",
        validators=[
            Optional(),
            FileAllowed(["jpg", "jpeg", "png", "gif"], "仅支持 jpg/jpeg/png/gif"),
            FileSize(max_size=10 * 1024 * 1024),
        ],
    )
    link_url = StringField("跳转链接", validators=[Optional(), Length(max=500)])
    title = StringField("标题", validators=[Optional(), Length(max=100)])
    desc_text = StringField("描述", validators=[Optional(), Length(max=200)])
    sort_num = IntegerField("排序", validators=[Optional(), NumberRange(min=0)], default=0)
    submit = SubmitField("保存")


class UploadImageForm(FlaskForm):
    image = FileField(
        "图片",
        validators=[
            DataRequired(),
            FileAllowed(["jpg", "jpeg", "png", "gif"], "仅支持 jpg/jpeg/png/gif"),
            FileSize(max_size=10 * 1024 * 1024),
        ],
    )


class CommentForm(FlaskForm):
    username = StringField("用户名", validators=[Optional(), Length(max=50)])
    content = TextAreaField("内容", validators=[DataRequired(), Length(max=2000)])


class ReplyForm(FlaskForm):
    username = StringField("用户名", validators=[Optional(), Length(max=50)])
    content = TextAreaField("内容", validators=[DataRequired(), Length(max=2000)])
