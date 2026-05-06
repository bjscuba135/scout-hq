// Scout HQ — minimal JS escape hatch
// json-enc extension (loaded in base.html) handles PATCH/POST → JSON automatically.
// This file provides small UI utilities only.

// ── Inline edit toggles ───────────────────────────────────────────────────────

function showEdit(showId, hideId) {
  // Close any other open edit form first so only one is ever active at a time
  document.querySelectorAll('[id$="-edit-form"]').forEach(function(form) {
    if (form.id !== showId) form.style.display = 'none';
  });
  document.querySelectorAll('[id$="-display"]').forEach(function(disp) {
    if (disp.id !== hideId) disp.style.display = '';
  });
  var show = document.getElementById(showId);
  var hide = document.getElementById(hideId);
  if (show) show.style.display = '';
  if (hide) hide.style.display = 'none';
}

function hideEdit(hideId, showId) {
  var hide = document.getElementById(hideId);
  var show = document.getElementById(showId);
  if (hide) hide.style.display = 'none';
  if (show) show.style.display = '';
}

// ── Entity suggestion type filter (client-side) ───────────────────────────────

function filterSuggest(btn, type) {
  btn.closest('.ep-type-chips').querySelectorAll('.chip').forEach(function(c) {
    c.classList.remove('active');
  });
  btn.classList.add('active');
  var body = btn.closest('.ep-suggest-body');
  if (!body) return;
  body.querySelectorAll('.suggest-item').forEach(function(item) {
    var matches = !type || (item.dataset.entityType || '') === type;
    item.style.display = matches ? '' : 'none';
  });
}

// Hide type filter chips while the search input has a value, restore when cleared
document.body.addEventListener('input', function(evt) {
  if (!evt.target.classList.contains('ep-search-input')) return;
  var chips = document.getElementById('ep-type-chips');
  if (chips) chips.style.display = evt.target.value.trim() ? 'none' : '';
});

// ── Copy task as prompt ───────────────────────────────────────────────────────

function copyTaskAsPrompt() {
  // Data lives on #task-main-col (left column of the two-column layout)
  var detail = document.getElementById('task-main-col') || document.getElementById('task-detail');
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

// ── Inject entity types into the attach form payload ─────────────────────────
// json-enc only sends entity_names (the checkbox values). This handler adds
// entity_types as a name→type dict so the backend can store the type.

document.body.addEventListener('htmx:configRequest', function(evt) {
  var elt = evt.detail.elt;
  if (!elt) return;
  var form = (elt.id === 'ep-attach-form') ? elt : (elt.closest ? elt.closest('#ep-attach-form') : null);
  if (!form) return;

  var types = {};
  form.querySelectorAll('.entity-cb:checked').forEach(function(cb) {
    var type = cb.dataset.type || (cb.closest('[data-entity-type]') || {}).dataset.entityType || '';
    if (cb.value) types[cb.value] = type;
  });
  if (Object.keys(types).length) {
    evt.detail.parameters.entity_types = types;
  }
});

// ── Clear note textarea after successful note append ─────────────────────────

document.body.addEventListener('htmx:afterSwap', function (evt) {
  // After a notes POST swaps in the refreshed detail, clear the note textarea
  // (the new DOM won't have a value, so nothing to do — but keep hook for future use)
});
