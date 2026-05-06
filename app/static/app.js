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
  const body     = detail.dataset.body     || '';

  const meta = [category, priority, status, due ? `due ${due}` : ''].filter(Boolean).join(' · ');
  const lines = [
    `Task: ${title}`,
    meta,
    '',
    body,
    '',
    '---',
    'Context: I am the Group Lead Volunteer (GLV) at 1st Beetley Scout Group, Beetley, Norfolk.',
  ].filter((l, i) => i < 2 || l !== '' || lines?.[i - 1] !== '');

  navigator.clipboard.writeText(lines.join('\n').trim()).then(() => {
    const btn = document.getElementById('copy-prompt-btn');
    if (!btn) return;
    const orig = btn.textContent;
    btn.textContent = '✓ Copied!';
    setTimeout(() => { btn.textContent = orig; }, 2000);
  });
}

// ── Clear note textarea after successful note append ─────────────────────────

document.body.addEventListener('htmx:afterSwap', function (evt) {
  // After a notes POST swaps in the refreshed detail, clear the note textarea
  // (the new DOM won't have a value, so nothing to do — but keep hook for future use)
});
