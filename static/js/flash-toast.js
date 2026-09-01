/* Flash 消息 → Bootstrap Toast（牛皮癣式提示，不占用页面布局）。
 * 消息由 base.html 以 <script type="application/json" id="flashData"> 注入，
 * 形如 [["success", "xxx"], ...]。使用 textContent 渲染正文，避免 XSS。 */
(function () {
    'use strict';

    var data = document.getElementById('flashData');
    var messages = [];
    if (data) {
        try { messages = JSON.parse(data.textContent); } catch (e) { messages = []; }
    }
    if (!messages || !messages.length) return;

    var container = document.getElementById('flashToastContainer');
    if (!container || typeof bootstrap === 'undefined') return;

    var ICON = {
        success: 'bi-check-circle-fill',
        danger: 'bi-x-circle-fill',
        error: 'bi-x-circle-fill',
        warning: 'bi-exclamation-triangle-fill',
        info: 'bi-info-circle-fill'
    };

    function normalize(cat) {
        return cat === 'error' ? 'danger' : (cat || 'info');
    }

    messages.forEach(function (pair) {
        var cat = normalize(pair[0]);
        var text = pair[1] || '';

        var toast = document.createElement('div');
        toast.className = 'toast flash-toast';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');

        var body = document.createElement('div');
        body.className = 'toast-body d-flex align-items-center gap-2';

        var icon = document.createElement('i');
        icon.className = 'bi ' + (ICON[cat] || ICON.info) + ' flash-toast-icon';

        var span = document.createElement('span');
        span.textContent = text;

        body.appendChild(icon);
        body.appendChild(span);
        toast.appendChild(body);

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'btn-close btn-close-white me-2 m-auto flash-toast-close';
        close.setAttribute('data-bs-dismiss', 'toast');
        close.setAttribute('aria-label', 'Close');
        toast.appendChild(close);

        container.appendChild(toast);
        var instance = new bootstrap.Toast(toast, { delay: 3500 });
        instance.show();
    });
})();
