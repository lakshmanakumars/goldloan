/* Live LTV recompute + field auto-fill for the Loan admin's gold-item inline.
 *
 * Two jobs:
 *
 * 1) Inline auto-fill (per row):
 *    - net_weight_g    = max(gross - stone, 0)   on gross/stone change
 *    - rate_per_gram_0 = rate for the selected carat (with 22ct fallback)
 *                                                 on purity_carat change
 *    Both respect manual overrides: once the user types their own value,
 *    we stop overwriting it (tracked via `dataset.lastAuto` per input).
 *
 * 2) Live LTV recompute (whole loan):
 *    - Reads #ltv-rates (JSON injected by LoanAdmin.render_change_form),
 *      the inline rows, and the principal input.
 *    - Writes #ltv-eligible-principal-live and #ltv-summary-live.
 *
 * Runs whenever the user types/changes a relevant field. Recompute is cheap
 * (handful of rows), so a debounce isn't needed.
 */
(function () {
    'use strict';

    function readRates() {
        var el = document.getElementById('ltv-rates');
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    }

    function fmtINR(x) {
        if (!isFinite(x)) x = 0;
        return x.toLocaleString('en-IN', {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
    }

    function rateForPurity(ltv, purity) {
        if (!ltv) return null;
        var key = Number(purity).toFixed(2);
        if (ltv.rates && ltv.rates[key] !== undefined) return ltv.rates[key];
        if (ltv.fallback_22ct) {
            return ltv.fallback_22ct * Number(purity) / 22.0;
        }
        return null;
    }

    // Effective rate for an inline row: user-typed value wins; otherwise
    // fall back to the tenant's stored GoldRate for that carat.
    function effectiveRate(row, ltv) {
        if (row.userRate && row.userRate > 0) return row.userRate;
        return rateForPurity(ltv, row.purity);
    }

    function readRows() {
        // The inline prefix is "items" (GoldItem.loan related_name).
        var rows = [];
        var grossInputs = document.querySelectorAll(
            'input[name^="items-"][name$="-gross_weight_g"]');
        grossInputs.forEach(function (g) {
            var m = g.name.match(/^items-(\d+)-gross_weight_g$/);
            if (!m) return;
            var i = m[1];

            // Skip rows marked for deletion.
            var del = document.querySelector(
                'input[name="items-' + i + '-DELETE"]');
            if (del && del.checked) return;

            var gross = parseFloat(g.value) || 0;
            var stoneEl = document.querySelector(
                'input[name="items-' + i + '-stone_weight_g"]');
            var stone = parseFloat(stoneEl && stoneEl.value) || 0;
            var netEl = document.querySelector(
                'input[name="items-' + i + '-net_weight_g"]');
            var netVal = parseFloat(netEl && netEl.value) || 0;
            var net = netVal > 0 ? netVal : Math.max(gross - stone, 0);

            var purityEl = document.querySelector(
                'input[name="items-' + i + '-purity_carat"]');
            var purity = parseFloat(purityEl && purityEl.value) || 22;

            var descEl = document.querySelector(
                'input[name="items-' + i + '-description"]');
            var desc = (descEl && descEl.value)
                ? descEl.value : ('Row ' + (parseInt(i, 10) + 1));

            // Capture whatever the user typed in the rate field — used in
            // preference to the JSON rate lookup so the LTV reflects the
            // form as-is, even on tenants with no GoldRate records yet.
            var rateEl = document.querySelector(
                'input[name="items-' + i + '-rate_per_gram_0"]');
            var userRate = parseFloat(rateEl && rateEl.value) || 0;

            if (net <= 0) return;
            rows.push({
                i: i, net: net, purity: purity, desc: desc,
                userRate: userRate,
            });
        });
        return rows;
    }

    function readCurrentPrincipal() {
        // djmoney: amount field is `<name>_0`, currency is `<name>_1`.
        var p = document.querySelector('input[name="principal_0"]')
             || document.querySelector('input[name="principal"]');
        return parseFloat(p && p.value) || 0;
    }

    function buildSummaryHTML(rows, gross, eligible, ltv) {
        if (!rows.length) {
            return '<span style="color:#6b7280">Add gold items above — the '
                 + 'LTV breakdown will appear here live.</span>';
        }
        var rowsHtml = rows.map(function (r) {
            var rate = effectiveRate(r, ltv);
            var rateText = rate == null
                ? '<span style="color:#b45309">no rate</span>'
                : '₹' + fmtINR(rate) + '/g';
            var value = rate == null ? 0 : (r.net * rate);
            return '<tr>'
                 + '<td style="padding:6px">' + escapeHtml(r.desc) + '</td>'
                 + '<td style="padding:6px;text-align:right">'
                 +   r.net.toFixed(3) + ' g</td>'
                 + '<td style="padding:6px;text-align:right">'
                 +   r.purity.toFixed(2) + ' ct</td>'
                 + '<td style="padding:6px;text-align:right">' + rateText
                 +   '</td>'
                 + '<td style="padding:6px;text-align:right"><b>₹'
                 +   fmtINR(value) + '</b></td>'
                 + '</tr>';
        }).join('');

        return '<table style="width:100%;border-collapse:collapse;'
             + 'font-size:13px">'
             + '<thead><tr style="background:#c46616;color:#fff">'
             +   '<th style="padding:6px;text-align:left">Item</th>'
             +   '<th style="padding:6px;text-align:right">Net wt</th>'
             +   '<th style="padding:6px;text-align:right">Purity</th>'
             +   '<th style="padding:6px;text-align:right">Rate / g</th>'
             +   '<th style="padding:6px;text-align:right">Value</th>'
             + '</tr></thead>'
             + '<tbody>' + rowsHtml + '</tbody>'
             + '<tfoot>'
             +   '<tr style="background:#fef3c7">'
             +     '<td colspan="4" style="padding:6px;text-align:right;'
             +     'font-weight:700">Gross gold value (live)</td>'
             +     '<td style="padding:6px;text-align:right;font-weight:700">'
             +     '₹' + fmtINR(gross) + '</td>'
             +   '</tr>'
             +   '<tr>'
             +     '<td colspan="4" style="padding:6px;text-align:right">'
             +     'Max LTV (' + ltv.max_ltv_pct + '%) → Eligible principal'
             +     '</td>'
             +     '<td style="padding:6px;text-align:right;font-weight:700">'
             +     '₹' + fmtINR(eligible) + '</td>'
             +   '</tr>'
             + '</tfoot></table>';
    }

    function buildEligibleHTML(rows, gross, eligible, current, ltv) {
        if (!rows.length) {
            return '<span style="color:#6b7280">Add gold items above — '
                 + 'eligible principal will appear here live.</span>';
        }
        var ok = current <= eligible;
        return '<div style="font-size:13px">'
             +   '<span style="font-size:16px;font-weight:700;'
             +   'font-variant-numeric:tabular-nums">₹' + fmtINR(eligible)
             +   '</span>'
             +   '<span style="color:#6b7280;margin-left:8px">= '
             +   ltv.max_ltv_pct + '% of ₹' + fmtINR(gross)
             +   ' gold value (live)</span>'
             +   '<div style="margin-top:4px;padding:4px 10px;'
             +   'border-radius:4px;display:inline-block;background:'
             +   (ok ? '#dcfce7' : '#fee2e2') + ';color:'
             +   (ok ? '#166534' : '#991b1b') + ';font-weight:600;'
             +   'font-size:12px">Current principal ₹' + fmtINR(current)
             +   ' is ' + (ok ? 'within' : 'ABOVE') + ' the LTV cap</div>'
             + '</div>';
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;',
            })[c];
        });
    }

    function recompute() {
        var ltv = readRates() || {max_ltv_pct: 75.0, rates: {}};
        var rows = readRows();
        var gross = 0;
        rows.forEach(function (r) {
            var rate = effectiveRate(r, ltv);
            if (rate != null) gross += r.net * rate;
        });
        var eligible = gross * Number(ltv.max_ltv_pct) / 100.0;
        var current = readCurrentPrincipal();

        var elig = document.getElementById('ltv-eligible-principal-live');
        if (elig) {
            elig.innerHTML = buildEligibleHTML(
                rows, gross, eligible, current, ltv);
        }
        var summary = document.getElementById('ltv-summary-live');
        if (summary) {
            summary.innerHTML = buildSummaryHTML(rows, gross, eligible, ltv);
        }
    }

    function isInterestingTarget(t) {
        if (!t || !t.name) return false;
        if (t.name.indexOf('items-') === 0) return true;
        if (t.name === 'principal_0' || t.name === 'principal') return true;
        return false;
    }

    // Set el.value, but only if the field is empty or still holds our last
    // auto-filled value. The moment the user types something different, we
    // stop overwriting it (their input wins).
    function setAuto(el, formattedValue) {
        if (!el) return;
        var current = (el.value || '').trim();
        var lastAuto = el.dataset.lastAuto || '';
        if (current === '' || current === lastAuto) {
            el.value = formattedValue;
            el.dataset.lastAuto = formattedValue;
        }
    }

    function rowEl(i, field) {
        return document.querySelector(
            'input[name="items-' + i + '-' + field + '"]');
    }

    function autoFillNet(i) {
        var netEl = rowEl(i, 'net_weight_g');
        if (!netEl) return;
        var grossRaw = (rowEl(i, 'gross_weight_g') || {}).value || '';
        var stoneRaw = (rowEl(i, 'stone_weight_g') || {}).value || '';
        if (grossRaw === '' && stoneRaw === '') return;
        var gross = parseFloat(grossRaw) || 0;
        var stone = parseFloat(stoneRaw) || 0;
        var net = Math.max(gross - stone, 0);
        setAuto(netEl, net.toFixed(3));
    }

    function autoFillRate(i, ltv) {
        ltv = ltv || readRates();
        if (!ltv) return;
        var rateEl = rowEl(i, 'rate_per_gram_0');
        if (!rateEl) return;
        var purityEl = rowEl(i, 'purity_carat');
        var purity = parseFloat(purityEl && purityEl.value) || 0;
        if (purity <= 0) return;
        var rate = rateForPurity(ltv, purity);
        if (rate == null) return;
        setAuto(rateEl, rate.toFixed(2));
    }

    function autoFillAll() {
        var ltv = readRates();
        document.querySelectorAll(
            'input[name^="items-"][name$="-gross_weight_g"]'
        ).forEach(function (g) {
            var m = g.name.match(/^items-(\d+)-gross_weight_g$/);
            if (!m) return;
            autoFillNet(m[1]);
            autoFillRate(m[1], ltv);
        });
    }

    function onEvent(e) {
        var t = e.target;
        if (!t || !t.name) return;
        var m = t.name.match(/^items-(\d+)-(.+)$/);
        if (m) {
            var i = m[1], field = m[2];
            if (field === 'gross_weight_g' || field === 'stone_weight_g') {
                autoFillNet(i);
            } else if (field === 'purity_carat') {
                autoFillRate(i);
            } else if (field === 'net_weight_g'
                       || field === 'rate_per_gram_0') {
                // User edited the auto-target directly — release our claim
                // so we don't overwrite their value on the next gross/stone
                // or purity change.
                t.dataset.lastAuto = '';
            }
        }
        if (isInterestingTarget(t)) recompute();
    }

    function init() {
        document.addEventListener('input', onEvent, true);
        document.addEventListener('change', onEvent, true);
        // Also catch "Add another" — fill defaults for the new row (purity
        // defaults to 22ct on the model, so we can fill rate immediately).
        document.addEventListener('click', function (e) {
            var t = e.target;
            if (t && t.closest && t.closest('.add-row')) {
                setTimeout(function () {
                    autoFillAll();
                    recompute();
                }, 0);
            }
        }, true);
        autoFillAll();
        recompute();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
