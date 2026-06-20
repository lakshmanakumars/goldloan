/* Attach flatpickr to all admin date inputs.
 *
 * Unfold/Django render date fields as <input class="vDateField"> wired to
 * Django's built-in admin calendar (enhanced by Unfold), which only steps one
 * month at a time and is painful for picking a distant year/month (e.g. a DOB
 * or a backdated loan). flatpickr gives a month dropdown + typeable year and
 * shows the value as dd-mm-yyyy, matching DATE_INPUT_FORMATS. We also hide
 * Django's redundant calendar icon so there is a single, consistent picker.
 */
(function () {
  function enhance(input) {
    if (input._flatpickr || typeof flatpickr === 'undefined') return;
    flatpickr(input, {
      dateFormat: 'd-m-Y',
      allowInput: true,          // still allow typing the date
      monthSelectorType: 'dropdown',
      disableMobile: true,       // use flatpickr (not native) for consistent format
    });
    // Django's DateTimeShortcuts injects a calendar icon / shortcuts as a
    // sibling of the input; remove it so only flatpickr remains.
    var shortcuts = input.parentNode &&
      input.parentNode.querySelector('.datetimeshortcuts');
    if (shortcuts) shortcuts.style.display = 'none';
  }

  function init(root) {
    (root || document).querySelectorAll('input.flatpickr-date').forEach(enhance);
  }

  // Run on `load` (after DOMContentLoaded) so Django's DateTimeShortcuts.js has
  // already injected its calendar icons and we can reliably hide them.
  window.addEventListener('load', function () {
    init(document);
    // Inline formsets (e.g. gold items on a loan) add rows after load.
    document.body.addEventListener('formset:added', function (e) {
      init(e.target);
    });
  });
})();
