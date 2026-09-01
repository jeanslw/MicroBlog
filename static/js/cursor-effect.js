/* 鼠标移动跟随粒子特效：移动鼠标时在光标处飘出柔和光点，上浮淡出。
 * 仅桌面端（pointer: fine）启用；粒子数量受限，不拦截鼠标事件。 */
(function () {
    'use strict';

    if (!window.matchMedia || !window.matchMedia('(pointer: fine)').matches) return;

    var container = document.createElement('div');
    container.id = 'cursorFx';
    container.setAttribute('aria-hidden', 'true');
    document.body.appendChild(container);

    var COLORS = ['#ffd166', '#7dd3fc', '#f9a8d4', '#86efac', '#c4b5fd', '#fca5a5'];
    var MAX = 36;
    var THROTTLE = 35;
    var last = 0;

    document.addEventListener('mousemove', function (e) {
        var now = Date.now();
        if (now - last < THROTTLE) return;
        last = now;
        if (container.childElementCount >= MAX) return;

        var p = document.createElement('span');
        var size = 3 + Math.random() * 5;
        p.style.left = e.clientX + 'px';
        p.style.top = e.clientY + 'px';
        p.style.width = size + 'px';
        p.style.height = size + 'px';
        p.style.background = COLORS[Math.floor(Math.random() * COLORS.length)];

        container.appendChild(p);
        requestAnimationFrame(function () {
            p.style.opacity = '0.75';
        });

        setTimeout(function () {
            p.style.transform = 'translate(-50%, -50%) translateY(-46px) scale(0.35)';
            p.style.opacity = '0';
            setTimeout(function () { if (p.parentNode) p.parentNode.removeChild(p); }, 950);
        }, 20);
    });
})();
