/* 语言一键切换：点一下中文、再点一下英文，来回切换（无下拉弹窗）。
 * 目标语言与跳转 URL 由 base.html 通过 data-next-lang / data-url 注入。 */
(function () {
    'use strict';

    var btn = document.getElementById('langToggleBtn');
    if (!btn) return;

    var next = btn.getAttribute('data-next-lang') || 'en';
    var url = btn.getAttribute('data-url') || '';

    btn.addEventListener('click', function () {
        if (url) window.location.href = url.replace('__LANG__', next);
    });
})();
