/**
 * theme-switcher.js - 背景风格切换器
 * 默认风格来自后台 SiteConfig.bg_style（base.html 输出到 body[data-bg]），
 * 前台用户可临时切换并持久化到 localStorage（key: blog-bg-style），
 * 优先于后台默认值。
 *
 * 切换按钮支持拖拽（鼠标/触摸），位置持久化到 localStorage
 * （key: blog-bg-switcher-pos）；拖拽距离小于阈值视为点击，展开/收起面板。
 */
(function () {
    'use strict';

    var STORAGE_KEY = 'blog-bg-style';
    var POS_KEY = 'blog-bg-switcher-pos';
    var DEFAULT_STYLE = document.body.getAttribute('data-bg') || 'bg1';
    var SUPPORTED = [];

    document.querySelectorAll('.theme-swatch').forEach(function (btn) {
        SUPPORTED.push(btn.getAttribute('data-theme'));
    });

    var switcher = document.getElementById('themeSwitcher');
    var toggle = document.getElementById('themeToggle');
    var panel = document.getElementById('themePanel');

    // ---------- 拖拽位置 ----------
    var DEFAULT_POS = { right: 20, bottom: 20 };
    var BTN_SIZE = 46; // 与 CSS 的 .theme-toggle 尺寸保持一致
    var DRAG_THRESHOLD = 6; // 移动超过该像素视为拖拽而非点击

    var pos = loadPos() || Object.assign({}, DEFAULT_POS);
    var dragging = false;
    var dragMoved = false;
    var startX = 0;
    var startY = 0;
    var startRight = 0;
    var startBottom = 0;

    function loadPos() {
        try {
            var raw = localStorage.getItem(POS_KEY);
            if (raw) {
                var p = JSON.parse(raw);
                if (typeof p.right === 'number' && typeof p.bottom === 'number') {
                    return p;
                }
            }
        } catch (e) { /* 隐私模式忽略 */ }
        return null;
    }

    function savePos() {
        try {
            localStorage.setItem(POS_KEY, JSON.stringify(pos));
        } catch (e) { /* 隐私模式忽略 */ }
    }

    function clampPos() {
        var vw = window.innerWidth;
        var vh = window.innerHeight;
        pos.right = Math.max(8, Math.min(vw - BTN_SIZE - 8, pos.right));
        pos.bottom = Math.max(8, Math.min(vh - BTN_SIZE - 8, pos.bottom));
    }

    function applyPos() {
        if (!switcher) return;
        clampPos();
        switcher.style.right = pos.right + 'px';
        switcher.style.bottom = pos.bottom + 'px';
        updatePanelDir();
    }

    // 面板方向自适应：按钮位于屏幕左半区时面板向右弹出，否则向左
    function updatePanelDir() {
        if (!panel) return;
        var centerX = window.innerWidth - pos.right - BTN_SIZE / 2;
        panel.classList.toggle('panel-right', centerX < window.innerWidth / 2);
    }

    function getPoint(e) {
        return e.touches ? e.touches[0] : e;
    }

    function onPointerDown(e) {
        var pt = getPoint(e);
        dragging = true;
        dragMoved = false;
        startX = pt.clientX;
        startY = pt.clientY;
        startRight = pos.right;
        startBottom = pos.bottom;
        if (toggle) toggle.classList.add('sw-dragging');
        e.preventDefault();
    }

    function onPointerMove(e) {
        if (!dragging || !switcher) return;
        var pt = getPoint(e);
        var dx = pt.clientX - startX;
        var dy = pt.clientY - startY;
        if (!dragMoved && (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)) {
            dragMoved = true;
        }
        if (dragMoved) {
            pos.right = startRight - dx;
            pos.bottom = startBottom - dy;
            applyPos();
        }
        e.preventDefault();
    }

    function onPointerUp() {
        if (!dragging) return;
        dragging = false;
        if (toggle) toggle.classList.remove('sw-dragging');
        if (dragMoved) {
            savePos();
            // 延迟复位，避免鼠标松开时立即触发的 click 打开面板
            setTimeout(function () { dragMoved = false; }, 200);
        }
    }

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
        applyPos();

        if (!toggle || !panel) {
            return;
        }

        toggle.addEventListener('click', function () {
            if (dragMoved) return; // 刚拖拽完，忽略本次点击
            panel.hidden = !panel.hidden;
        });

        // 点击面板外部时收起
        document.addEventListener('click', function (ev) {
            if (!panel.hidden && !ev.target.closest('#themeSwitcher')) {
                panel.hidden = true;
            }
        });

        // 拖拽（鼠标 + 触摸）
        toggle.addEventListener('mousedown', onPointerDown);
        document.addEventListener('mousemove', onPointerMove);
        document.addEventListener('mouseup', onPointerUp);
        toggle.addEventListener('touchstart', onPointerDown, { passive: false });
        document.addEventListener('touchmove', onPointerMove, { passive: false });
        document.addEventListener('touchend', onPointerUp);
        document.addEventListener('touchcancel', onPointerUp);

        window.addEventListener('resize', function () {
            if (!dragging) applyPos();
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
