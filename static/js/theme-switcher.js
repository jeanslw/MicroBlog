/**
 * theme-switcher.js - 背景风格切换器
 * 默认风格来自后台 SiteConfig.bg_style（base.html 输出到 body[data-bg]），
 * 前台用户可临时切换并持久化到 localStorage（key: blog-bg-style），
 * 优先于后台默认值。
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'blog-bg-style';
    var DEFAULT_STYLE = document.body.getAttribute('data-bg') || 'bg1';
    var SUPPORTED = [];

    document.querySelectorAll('.theme-swatch').forEach(function (btn) {
        SUPPORTED.push(btn.getAttribute('data-theme'));
    });

    function currentStyle() {
        var saved = null;
        try {
            saved = localStorage.getItem(STORAGE_KEY);
        } catch (e) { /* 忽略隐私模式异常 */ }
        if (saved && SUPPORTED.indexOf(saved) !== -1) {
            return saved;
        }
        return (SUPPORTED.indexOf(DEFAULT_STYLE) !== -1) ? DEFAULT_STYLE : 'bg1';
    }

    function applyStyle(name) {
        document.body.setAttribute('data-bg', name);
    }

    function setActive(name) {
        document.querySelectorAll('.theme-swatch').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-theme') === name);
        });
    }

    function init() {
        var style = currentStyle();
        applyStyle(style);
        setActive(style);

        var toggle = document.getElementById('themeToggle');
        var panel = document.getElementById('themePanel');
        if (!toggle || !panel) {
            return;
        }

        toggle.addEventListener('click', function () {
            panel.hidden = !panel.hidden;
        });

        // 点击面板外部时收起
        document.addEventListener('click', function (ev) {
            if (!panel.hidden && !ev.target.closest('#themeSwitcher')) {
                panel.hidden = true;
            }
        });

        document.querySelectorAll('.theme-swatch').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var name = btn.getAttribute('data-theme');
                applyStyle(name);
                setActive(name);
                try {
                    localStorage.setItem(STORAGE_KEY, name);
                } catch (e) { /* 隐私模式下静默失败 */ }
                panel.hidden = true;
            });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
