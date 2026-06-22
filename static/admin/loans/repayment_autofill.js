/* Repayment admin add/change form: when the user picks a loan, pre-fill
 * the interest-paid and principal-paid amounts from the loan's live balance.
 *
 *   interest_paid_0   ← loan.interest_due_now (full outstanding interest)
 *   principal_paid_0  ← 0   (most repayments are interest-only — the user
 *                            can bump it for a partial or full close-out)
 *
 * Source: /admin/loans/api/<id>/balance.json (loan_balance_json view).
 *
 * User overrides are respected — once the user types their own value into a
 * money field, we stop overwriting it (tracked via dataset.lastAuto).
 */
(function () {
    'use strict';

    var BALANCE_URL = '/admin/loans/api/{id}/balance.json';

    function setAuto(el, value) {
        if (!el) return;
        var current = (el.value || '').trim();
        var lastAuto = el.dataset.lastAuto || '';
        if (current === '' || current === lastAuto || current === '0' ||
            current === '0.00') {
            el.value = value;
            el.dataset.lastAuto = value;
        }
    }

    function showHint(balance) {
        var anchor = document.querySelector('.field-loan')
                  || document.querySelector('#id_loan');
        if (!anchor) return;
        var existing = document.getElementById('repayment-balance-hint');
        if (existing) existing.remove();
        if (!balance) return;
        var box = document.createElement('div');
        box.id = 'repayment-balance-hint';
        box.style.cssText = 'margin:8px 0;padding:8px 12px;border-radius:6px;'
            + 'background:#fef3c7;border:1px solid #fde68a;font-size:13px;'
            + 'max-width:560px';
        box.innerHTML =
            '<b>' + escapeHtml(balance.loan_no) + '</b> balance: '
          + 'outstanding principal <b>₹' + fmtINR(balance.outstanding_principal)
          + '</b> · interest due <b style="color:#991b1b">₹'
          + fmtINR(balance.interest_due_now) + '</b> '
          + '<span style="color:#6b7280">(monthly ₹'
          + fmtINR(balance.monthly_interest)
          + (balance.days_outstanding > 30
                ? ', pro-rated over ' + balance.days_outstanding + ' days'
                : ' for first 30 days')
          + ')</span>';
        (anchor.parentNode || anchor).insertBefore(box, anchor.nextSibling);
    }

    function fmtINR(s) {
        var n = parseFloat(s) || 0;
        return n.toLocaleString('en-IN', {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
    }

    function escapeHtml(s) {
        return String(s || '').replace(/[&<>"']/g, function (c) {
            return ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;',
            })[c];
        });
    }

    function fetchAndFill(loanId) {
        if (!loanId) {
            showHint(null);
            return;
        }
        var url = BALANCE_URL.replace('{id}', encodeURIComponent(loanId));
        fetch(url, {credentials: 'same-origin'})
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (data) {
                var interestEl = document.getElementById('id_interest_paid_0');
                var principalEl = document.getElementById('id_principal_paid_0');
                if (interestEl) {
                    setAuto(interestEl, Number(data.interest_due_now)
                        .toFixed(2));
                }
                if (principalEl) {
                    // Default principal-paid to 0: most repayments are
                    // interest-only. User bumps it for partial/full close.
                    setAuto(principalEl, '0.00');
                }
                showHint(data);
            })
            .catch(function () { showHint(null); });
    }

    function init() {
        var loanSel = document.getElementById('id_loan');
        if (!loanSel) return;

        // Django admin's autocomplete_fields uses Select2 under the hood.
        // Select2 dispatches a native 'change' on the underlying <select>.
        loanSel.addEventListener('change', function () {
            fetchAndFill(loanSel.value);
        });

        // If the form was loaded with a loan pre-selected (e.g. edit form
        // or via querystring), populate the hint immediately. We do NOT
        // overwrite existing amounts here — the form already has them.
        if (loanSel.value) {
            // Only show the hint; don't auto-fill (existing form values win).
            var url = BALANCE_URL.replace(
                '{id}', encodeURIComponent(loanSel.value));
            fetch(url, {credentials: 'same-origin'})
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) { if (data) showHint(data); })
                .catch(function () {});
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
