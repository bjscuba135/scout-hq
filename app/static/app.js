// Scout HQ — minimal JS escape hatch
// HTMX handles most interactivity; this file fills the gaps.

// Convert HTMX PATCH/POST payloads to JSON so FastAPI's Pydantic models parse correctly.
document.body.addEventListener('htmx:configRequest', function (evt) {
  const verb = evt.detail.verb;
  if (verb === 'patch' || verb === 'post') {
    const params = evt.detail.parameters;
    if (params && Object.keys(params).length > 0) {
      evt.detail.parameters = JSON.stringify(params);
      evt.detail.headers['Content-Type'] = 'application/json';
    }
  }
});
