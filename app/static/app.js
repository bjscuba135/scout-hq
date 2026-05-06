// Scout HQ — minimal JS escape hatch
// json-enc extension (loaded in base.html) handles PATCH/POST → JSON automatically.
// This file provides small UI utilities only.

// ── Inline edit toggles ───────────────────────────────────────────────────────

function showEdit(showId, hideId) {
  const show = document.getElementById(showId);
  const hide = document.getElementById(hideId);
  if (show) show.style.display = '';
  if (hide) hide.style.display = 'none';
}

function hideEdit(hideId, showId) {
  const hide = document.getElementById(hideId);
  const show = document.getElementById(showId);
  if (hide) hide.style.display = 'none';
  if (show) show.style.display = '';
}

// ── Copy task as prompt ───────────────────────────────────────────────────────

function copyTaskAsPrompt() {
  const detail = document.getElementById('task-detail');
  if (!detail) return;

  const title    = detail.dataset.title    || '';
  const category = detail.dataset.category || '';
  const priority = detail.dataset.priority || '';
  const status   = detail.dataset.status   || '';
  const due      = detail.dataset.due      || '';
  // Read body text from the DOM so HTML entities decode naturally
  const bodyEl   = detail.querySelector('.task-body-content');
  const body     = bodyEl ? bodyEl.textContent.trim() : (detail.dataset.body || '');

  const meta = [category, priority, status, due ? 'due ' + due : ''].filter(Boolean).join(' · ');

  const parts = ['Task: ' + title];
  if (meta) parts.push(meta);
  if (body) parts.push('', body);
  parts.push('', '---', 'Context: I am the Group Lead Volunteer (GLV) at 1st Beetley Scout Group, Beetley, Norfolk.');

  const text = parts.join('\n').trim();
  _copyText(text);
}

function _copyText(text) {
  // Modern Clipboard API requires HTTPS/localhost. Fall back to execCommand on plain HTTP.
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(_flashCopyBtn).catch(function(e) {
      console.warn('Clipboard API failed, falling back', e);
      _execCommandCopy(text);
    });
  } else {
    _execCommandCopy(text);
  }
}

function _execCommandCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;pointer-events:none';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try {
    document.execCommand('copy');
    _flashCopyBtn();
  } catch (e) {
    console.error('Copy failed:', e);
  }
  document.body.removeChild(ta);
}

function _flashCopyBtn() {
  const btn = document.getElementById('copy-prompt-btn');
  if (!btn) return;
  const orig = btn.textContent;
  btn.textContent = '✓ Copied!';
  setTimeout(function() { btn.textContent = orig; }, 2000);
}

// ── Clear note textarea after successful note append ─────────────────────────

document.body.addEventListener('htmx:afterSwap', function (evt) {
  // After a notes POST swaps in the refreshed detail, clear the note textarea
  // (the new DOM won't have a value, so nothing to do — but keep hook for future use)
});
