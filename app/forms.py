"""Flask-WTF 表单类。

所有写操作通过表单类统一校验,自动附带 CSRF token。
字段名尽量保持与原有 HTML form 字段一致,减少模板改动。
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileSize
from wtforms import (
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import (
    DataRequired,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)


class LoginForm(FlaskForm):
    username = StringField("账号", validators=[DataRequired(), Length(max=50)])
    password = PasswordField("密码", validators=[DataRequired()])
    submit = SubmitField("登录")


class ChangePwdForm(FlaskForm):
    old_pwd = PasswordField("原密码", validators=[DataRequired()])
    new_pwd = PasswordField("新密码",
                            validators=[DataRequired(), Length(min=6, max=128)])
    confirm_pwd = PasswordField("确认新密码", validators=[DataRequired()])

    def validate_confirm_pwd(self, field):
        if field.data != self.new_pwd.data:
            raise ValidationError("两次输入的新密码不一致")


class SiteSettingForm(FlaskForm):
    site_name = StringField("站点名称",
                            validators=[DataRequired(), Length(max=100)])
    submit = SubmitField("保存")


class CategoryForm(FlaskForm):
    cat_name = StringField("栏目名称",
                           validators=[DataRequired(), Length(max=60)])
    tag_text = StringField("标签", validators=[Optional(), Length(max=60)])
    submit = SubmitField("新增栏目")


class ArticleForm(FlaskForm):
    title = StringField("标题", validators=[DataRequired(), Length(max=500)])
    content = TextAreaField("正文", validators=[DataRequired()])
    status = SelectField("状态", choices=[("draft", "草稿"), ("publish", "发布")],
                         default="draft")
    category_id = SelectField("栏目", coerce=int, validators=[Optional()])
    submit = SubmitField("保存")


class BannerForm(FlaskForm):
    banner_img = FileField("轮播图", validators=[
        Optional(),
        FileAllowed(["jpg", "jpeg", "png", "gif"], "仅支持 jpg/jpeg/png/gif"),
        FileSize(max_size=10 * 1024 * 1024),
    ])
    link_url = StringField("跳转链接", validators=[Optional(), Length(max=500)])
    title = StringField("标题", validators=[Optional(), Length(max=100)])
    desc_text = StringField("描述", validators=[Optional(), Length(max=200)])
    sort_num = IntegerField("排序", validators=[Optional(), NumberRange(min=0)],
                            default=0)
    submit = SubmitField("保存")


class UploadImageForm(FlaskForm):
    image = FileField("图片", validators=[
        DataRequired(),
        FileAllowed(["jpg", "jpeg", "png", "gif"], "仅支持 jpg/jpeg/png/gif"),
        FileSize(max_size=10 * 1024 * 1024),
    ])


class CommentForm(FlaskForm):
    username = StringField("用户名", validators=[Optional(), Length(max=50)])
    content = TextAreaField("内容", validators=[DataRequired(), Length(max=2000)])


class ReplyForm(FlaskForm):
    username = StringField("用户名", validators=[Optional(), Length(max=50)])
    content = TextAreaField("内容", validators=[DataRequired(), Length(max=2000)])
