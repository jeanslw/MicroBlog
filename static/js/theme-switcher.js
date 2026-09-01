/**
 * theme-switcher.js - 背景风格切换器
 * 通过 body[data-bg="..."] 切换 themes.css 中定义的背景风格，
 * 选择结果持久化到 localStorage（key: blog-bg-style）。
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'blog-bg-style';
    var DEFAULT_STYLE = 'aurora';
    var SUPPORTED = ['aurora', 'stars', 'gradient', 'bubbles', 'classic'];

    function currentStyle() {
        try {
            return localStorage.getItem(STORAGE_KEY) || DEFAULT_STYLE;
        } catch (e) {
            return DEFAULT_STYLE;
        }
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
        if (SUPPORTED.indexOf(style) === -1) {
            style = DEFAULT_STYLE;
        }
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
