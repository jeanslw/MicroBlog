/* 语言一键切换:点一下中文,再点一下英文,来回切换(无下拉弹窗).
 * 目标语言与跳转 URL 由 base.html 通过 data-next-lang / data-url 注入. */
(function () {
    'use strict';

    var btn = document.getElementById('langToggleBtn');
    if (!btn) return;

    var next = btn.getAttribute('data-next-lang') || 'en';
    var url = btn.getAttribute('data-url') || '';
    var tokenMeta = document.querySelector('meta[name="csrf-token"]');

    // 切换语言会改写 session，必须走 POST 携带 CSRF token：
    // CSRFProtect 只拦截 POST/PUT/DELETE/PATCH，GET 不受保护，
    // 外站可用 <img src=".../set_lang/en"> 跨站修改访客语言偏好
    btn.addEventListener('click', function () {
        if (!url) return;
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = url.replace('__LANG__', next);
        if (tokenMeta) {
            var input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'csrf_token';
            input.value = tokenMeta.getAttribute('content');
            form.appendChild(input);
        }
        document.body.appendChild(form);
        form.submit();
    });
})();
