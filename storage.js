/* A synchronous editor store backed by debounced, revision-checked SQLite saves. */
window.openMindBoardStorage = async function () {
  const indicator = document.getElementById('saveStatus');
  const response = await fetch('/api/state', {cache: 'no-store', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error('Could not load boards from the server.');
  const initial = await response.json();
  let values = initial.storage;
  let revision = initial.revision;
  let version = 0, savedVersion = 0, timer, saving = false, blocked = false;

  function show(message) { indicator.textContent = message; }
  function changed() {
    version++;
    if (blocked) return;
    show('Unsaved changes');
    clearTimeout(timer);
    timer = setTimeout(flush, 400);
  }
  async function flush() {
    if (saving || blocked || version === savedVersion) return;
    saving = true;
    const writingVersion = version;
    show('Saving…');
    try {
      const result = await fetch('/api/state', {
        method: 'PUT',
        signal: AbortSignal.timeout(15000),
        headers: {'Content-Type': 'application/json', 'X-Mindboard': '1'},
        body: JSON.stringify({revision, storage: values}),
      });
      if (result.status === 409 || result.status === 413 || result.status === 422) {
        blocked = true;
        show(result.status === 409
          ? 'Changed elsewhere. Export your changes, then reload.'
          : 'Cannot save this collection. Export a backup before reloading.');
        const backup = document.createElement('button');
        backup.className = 'btn';
        backup.textContent = 'Export unsaved changes';
        backup.onclick = function () {
          const ix = JSON.parse(values['mindboard-index-v1']);
          window.downloadMindBoards({app: 'mindboard', version: 2,
            exported: new Date().toISOString(), boards: ix.list.map(function (item) {
              return {name: item.name, data: JSON.parse(values['mindboard-board-' + item.id])};
            })});
        };
        indicator.after(backup);
        return;
      }
      if (!result.ok) throw new Error('Save failed');
      revision = (await result.json()).revision;
      savedVersion = writingVersion;
      show(version === savedVersion ? 'Saved to SQLite' : 'Unsaved changes');
    } catch (error) {
      show('Server unavailable — changes are not saved. Retrying…');
    } finally {
      saving = false;
      if (!blocked && version !== savedVersion) {
        clearTimeout(timer);
        timer = setTimeout(flush, 2000);
      }
    }
  }
  window.addEventListener('beforeunload', function (event) {
    if (version !== savedVersion) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flush();
  });
  show('Saved to SQLite');
  return {
    getItem: function (key) { return values[key] ?? null; },
    setItem: function (key, value) {
      if (values[key] !== value) { values[key] = value; changed(); }
    },
    removeItem: function (key) {
      if (Object.hasOwn(values, key)) { delete values[key]; changed(); }
    },
  };
};

window.downloadMindBoards = function (data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'mindboards-' + new Date().toISOString().slice(0, 10) + '.json';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
};