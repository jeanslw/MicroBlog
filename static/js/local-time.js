(function () {
    'use strict';

    var configEl = document.getElementById('tzConfig');
    var config = { siteTimezone: 'UTC', followBrowser: true, cookieName: 'blog_tz' };
    if (configEl) {
        try {
            var parsed = JSON.parse(configEl.textContent || '{}');
            if (parsed.siteTimezone) config.siteTimezone = parsed.siteTimezone;
            if (typeof parsed.followBrowser === 'boolean') config.followBrowser = parsed.followBrowser;
            if (parsed.cookieName) config.cookieName = parsed.cookieName;
        } catch (e) {
            config = { siteTimezone: 'UTC', followBrowser: true, cookieName: 'blog_tz' };
        }
    }

    var browserTz = 'UTC';
    try {
        browserTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch (e) {
        browserTz = 'UTC';
    }

    if (config.followBrowser) {
        document.cookie = config.cookieName + '=' + encodeURIComponent(browserTz) + '; path=/; max-age=31536000; SameSite=Lax';
    }

    function parseUtc(raw) {
        if (!raw) return null;
        var text = String(raw).trim();
        if (!text) return null;
        var normalized = text;
        if (text.indexOf('T') === -1 && text.indexOf(' ') !== -1) {
            normalized = text.replace(' ', 'T') + 'Z';
        }
        var date = new Date(normalized);
        return isNaN(date.getTime()) ? null : date;
    }

    function pad(value) {
        return String(value).padStart(2, '0');
    }

    function partsFor(date, tz) {
        var formatter;
        try {
            formatter = new Intl.DateTimeFormat('en-US', {
                timeZone: tz,
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hourCycle: 'h23'
            });
        } catch (e) {
            return null;
        }
        var values = {};
        formatter.formatToParts(date).forEach(function (part) {
            values[part.type] = part.value;
        });
        return values;
    }

    function offsetLabel(date, tz, parts) {
        if (!parts) return tz;
        var asUtc = Date.UTC(
            Number(parts.year),
            Number(parts.month) - 1,
            Number(parts.day),
            Number(parts.hour),
            Number(parts.minute),
            Number(parts.second)
        );
        var minutes = Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
        if (minutes === 0) return 'UTC';
        var sign = minutes > 0 ? '+' : '-';
        var absolute = Math.abs(minutes);
        return 'UTC' + sign + pad(Math.floor(absolute / 60)) + ':' + pad(absolute % 60);
    }

    function formatFor(date, tz) {
        var parts = partsFor(date, tz);
        if (!parts) return null;
        var clock = parts.year + '-' + parts.month + '-' + parts.day + ' ' +
            parts.hour + ':' + parts.minute + ':' + parts.second;
        return clock + ' ' + offsetLabel(date, tz, parts);
    }

    function render() {
        var siteTz = config.followBrowser ? browserTz : config.siteTimezone;
        document.querySelectorAll('time.local-time[data-utc]').forEach(function (el) {
            var raw = el.getAttribute('data-utc');
            var date = parseUtc(raw);
            if (!date) return;
            var tz = el.hasAttribute('data-force-browser') ? browserTz : siteTz;
            var text = formatFor(date, tz);
            if (!text) return;
            el.setAttribute('title', raw);
            el.textContent = text;
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', render);
    } else {
        render();
    }
})();
