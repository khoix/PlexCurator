const app = document.querySelector('#app');
const state = { items: [], total: 0, stats: {}, status: null, selected: '', nav: 'all', query: '', flagged: true, offset: 0, limit: 65, busy: false, providerOrder: 'aired', selectedIds: new Set(), lookups: new Map(), matches: [], posters: [], showLog: false, showConnect: false, mobileNavOpen: false, connectionDraft: null, logs: [], lookupMessage: '', toast: '', lastRefresh: 0, yearBatchReport: null, yearBatchProgress: '', renamePreflight: '', lastApplyResults: [], showApplyResults: false, scanBusy: false, scanReport: null, scannedRenames: new Set(), posterMessage: '', matchMessage: '', folderPreflight: '' };
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] || c));
const api = async (path, method = 'GET', body) => {
    const res = await fetch('/api' + path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
    const data = await res.json();
    if (!res.ok)
        throw new Error(data?.error || 'Request failed');
    return data;
};
const toast = (message) => { state.toast = message; const node = document.querySelector('#toast'); if (node) {
    node.textContent = message;
    node.classList.add('show');
    setTimeout(() => node.classList.remove('show'), 4500);
} };
const icon = (name, sz = 18) => {
    const paths = {
        library: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        layers: '<rect x="3" y="4" width="18" height="5" rx="1"/><rect x="3" y="11" width="18" height="5" rx="1"/><path d="M3 19h18"/>',
        search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
        check: '<path d="m4 12 5 5L20 6"/>',
        alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6m0 4v.1"/>',
        arrow: '<path d="m9 18 6-6-6-6"/>',
        spark: '<path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2Z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/>',
        upload: '<path d="M12 16V3m-5 5 5-5 5 5"/><path d="M4 16v5h16v-5"/>',
        download: '<path d="M12 3v13m-5-5 5 5 5-5"/><path d="M4 19v2h16v-2"/>',
        lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
        settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M4.9 4.9l2.2 2.2m9.8 9.8 2.2 2.2M19.1 4.9l-2.2 2.2m-9.8 9.8-2.2 2.2"/>',
        film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 3v18M16 3v18M3 8h5m-5 8h5m8-8h5m-5 8h5"/>',
        refresh: '<path d="M20 11a8 8 0 0 0-14-5L3 9m0-6v6h6M4 13a8 8 0 0 0 14 5l3-3m0 6v-6h-6"/>',
        history: '<path d="M3 12a9 9 0 1 0 3-7M3 3v5h5"/><path d="M12 7v5l4 2"/>',
        x: '<path d="M18 6 6 18M6 6l12 12"/>',
        file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
        bolt: '<path d="m13 2-9 12h7l-1 8 10-12h-7l0-8"/>',
        filter: '<path d="M4 6h16M7 12h10M10 18h4"/>',
        external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5H5V6h5"/>',
    };
    return `<svg width="${sz}" height="${sz}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
};
function selected() { return state.items.find(x => x.plex_id === state.selected) || null; }
const n = (value) => (value || 0).toLocaleString();
function sidebar() {
    const menu = [['all', 'All media', 'library'], ['Movie', 'Movies', 'film'], ['Show', 'TV shows', 'layers'], ['Episode', 'Episodes', 'file'], ['proposals', 'Proposals', 'check']];
    return `<aside class="sidebar" aria-label="Library navigation"><div class="brand"><span class="brand-symbol">${icon('layers', 22)}</span><div><div class="brand-title">PLEX<span>CURATOR</span></div><div class="brand-sub">Library intelligence</div></div></div><button type="button" class="nav-close icon-button" data-action="toggle-mobile-nav" aria-label="Close navigation">${icon('x', 20)}</button><div class="nav-group-label">WORKSPACE</div><nav class="nav">${menu.map(([id, label, ic]) => `<button class="nav-item ${state.nav === id ? 'active' : ''}" data-nav="${id}">${icon(ic)}<span>${label}</span><span class="nav-count">${id === 'all' ? n(state.status?.total) : n(state.stats[id])}</span></button>`).join('')}</nav><div class="sidebar-divider"></div><div class="nav-group-label">TOOLS</div><nav class="nav"><button class="nav-item" data-action="logs">${icon('history')}<span>Change history</span></button><button class="nav-item" data-action="export">${icon('download')}<span>Export findings</span></button></nav><div class="sidebar-bottom"><div class="secure-block">${icon('lock', 16)}<div><b>Local-first</b><span>Database is read-only. Changes require approval.</span></div></div><div class="version">CURATOR v0.8 · WINDOWS / MAC / LINUX</div></div></aside>`;
}
function metrics() {
    const cards = [['Records indexed', n(state.status?.total), 'library'], ['Needs review', n(state.stats.flagged), 'alert'], ['Approved', n(state.stats.reviewed), 'check']];
    return `<div class="metric-grid">${cards.map(([label, num, ic]) => `<div class="metric"><div class="metric-icon">${icon(ic, 19)}</div><div><div class="metric-value">${num}</div><div class="metric-label">${label}</div></div></div>`).join('')}<div class="metric has-pill"><div class="metric-icon">${icon('bolt', 19)}</div><div><div class="metric-value status-word ${state.status?.plex_token ? 'green' : 'amber'}">${state.status?.plex_token ? 'Ready' : 'No token'}</div><div class="metric-label">Plex API</div></div></div></div>`;
}
function listRow(item) {
    const d = item.diagnostic;
    const active = state.selected === item.plex_id;
    const isFlag = d.issues.length > 0;
    const hasProposal = ['title', 'year', 'filename', 'folder', 'poster_url', 'poster_key', 'match_guid'].some(k => Boolean(item.decision[k]));
    return `<div class="media-row ${active ? 'selected' : ''}" data-id="${esc(item.plex_id)}" role="button" tabindex="0"><label class="pick" onclick="event.stopPropagation()"><input type="checkbox" data-select="${esc(item.plex_id)}" ${state.selectedIds.has(item.plex_id) ? 'checked' : ''} aria-label="Select record ${esc(item.plex_id)}"/></label><span class="media-type-icon ${item.type.toLowerCase()}">${icon(item.type === 'Movie' ? 'film' : item.type === 'Show' ? 'layers' : 'file', 18)}</span><div class="media-info"><b>${esc(item.plex_title || 'Untitled')}</b><span>${esc(item.type === 'Episode' ? `${item.series_title || 'Unknown series'} · ` : '')}${esc((item.file_path || item.library || '').split('/').slice(-2).join('/'))}</span></div><div class="media-meta">${item.year ? `<span>${esc(item.year)}</span>` : ''}<small> #${esc(item.plex_id)}</small></div><div class="issue-tag ${hasProposal && !item.decision.approved ? 'proposal' : isFlag ? 'issue' : 'clean'}">${item.decision.approved ? 'Approved' : hasProposal ? 'Pending approval' : isFlag ? `${d.issues.length} issue${d.issues.length > 1 ? 's' : ''}` : 'Looks good'}</div><span class="row-arrow">${icon('arrow', 18)}</span></div>`;
}
function main() { return `<section class="work-area"><div class="top"><div class="crumb">MY LIBRARY <span>/</span> METADATA WORKSPACE</div><div class="connection ${state.status?.plex_token ? 'connected' : ''}"><span class="dot"></span>${state.status?.ssh_connected ? 'SSH connected' : state.status?.plex_token ? 'Plex connected' : 'Not connected'}</div></div><div class="page-heading"><div><div class="eyebrow">BATCH METADATA EDITOR</div><h1>Library health<span class="heading-dot">.</span></h1><p>Find mismatches. Cross-check sources. Apply only what you approve.</p></div><div class="primary-actions"><button class="btn btn-primary" data-action="connect-ssh">${icon('lock')} ${state.status?.ssh_connected ? 'Change server' : 'Connect via SSH'}</button>${state.status?.ssh_connected ? '<button class="btn btn-plain" data-action="disconnect-ssh">Disconnect</button>' : ''}<button class="btn btn-plain" data-action="import">${icon('upload')} Import CSV</button><button class="btn btn-plain" data-action="db">${icon('refresh')} Refresh DB</button></div></div>${metrics()}<div class="toolbar"><div class="toolbar-top"><h2>${state.nav === 'proposals' ? 'Proposals' : 'Media inventory'} <span class="heading-count">${n(state.total)}</span></h2><div class="toolbar-actions"><button class="btn btn-subtle" data-action="batch-years" ${state.busy ? 'disabled' : ''}>${icon('bolt', 17)} Verify & fix years</button><button class="btn btn-subtle" data-action="batch-lookup" ${state.busy ? 'disabled' : ''}>${icon('spark', 17)} Analyze selected</button><button class="btn btn-dark" data-action="apply" ${state.busy ? 'disabled' : ''}>${icon('check', 17)} Apply approved</button></div></div><div class="tool-controls"><label class="search-field">${icon('search')}<input id="search" placeholder="Search title, filename, ID..." value="${esc(state.query)}"/></label><button class="toggle ${state.flagged ? 'on' : ''}" data-action="flagged">${icon('filter', 16)} Issues only <span>${state.flagged ? 'ON' : 'OFF'}</span></button><div class="selected-counter">${state.selectedIds.size} selected</div></div></div><div class="table-area"><div class="table-head"><span><input id="pick-all" type="checkbox" aria-label="Select visible rows"/></span><span>MEDIA TITLE / FILE</span><span>YEAR / ID</span><span>STATUS</span><span></span></div><div class="rows">${state.items.length ? state.items.map(listRow).join('') : `<div class="empty"><div class="empty-icon">${icon('search', 30)}</div><h3>${state.status?.total ? 'No matching records' : 'No library loaded yet'}</h3><p>${state.status?.total ? 'Adjust your filters to see more records.' : 'Connect to the Plex server via SSH, or import an audit CSV.'}</p></div>`}</div><div class="pagination"><span>Showing ${state.items.length ? state.offset + 1 : 0}–${Math.min(state.offset + state.limit, state.total)} of ${n(state.total)}</span><div><button class="btn btn-plain small" data-action="prev" ${state.offset === 0 ? 'disabled' : ''}>Previous</button><button class="btn btn-plain small" data-action="next" ${state.offset + state.limit >= state.total ? 'disabled' : ''}>Next</button></div></div></div><div class="footer-note">${icon('lock', 14)} No database writes. Plex API and filesystem changes are audited separately.</div></section>`; }
function inspector() {
    const item = selected();
    if (!item)
        return `<aside class="inspector"><div class="inspector-head"><div>REVIEW DESK</div><span class="status-chip">NO SELECTION</span></div><div class="inspector-empty"><div class="graphic">${icon('spark', 38)}</div><h3>Pick a record</h3><p>Select an item to inspect file clues, compare provider metadata, and build a safe change proposal.</p><div class="inspector-hint">${icon('check', 18)} Changes are staged before applying</div></div></aside>`;
    const d = item.decision || {};
    const diag = item.diagnostic;
    const candidates = state.lookups.get(item.plex_id) || item.candidates || [];
    const flagged = diag.issues.length > 0;
    return `<aside class="inspector"><div class="inspector-head"><div><span class="mobile-back-label">EDIT MEDIA / </span>REVIEW DESK <span>#${esc(item.plex_id)}</span></div><button class="icon-button" data-action="close" aria-label="Close inspector">${icon('x', 17)}</button></div><div class="inspector-scroll"><div class="hero"><div class="hero-poster">${state.status?.plex_token ? `<img src="/api/poster/${encodeURIComponent(item.plex_id)}" onerror="this.style.display='none'" alt="Current Plex artwork"/>` : ''}<span class="poster-fallback">${icon('film', 34)}</span></div><div class="hero-text"><span class="media-kind">${esc(item.type)} ${esc(item.year || '')}</span><h3>${esc(item.plex_title || 'Untitled')}</h3><span class="series-name">${esc(item.series_title || item.library || '')}</span>${item.collections ? `<div class="collection-hint">Collection: ${esc(item.collections)}</div>` : ''}<div class="hero-tags"><span class="${flagged ? 'warn-pill' : 'good-pill'}">${flagged ? `${diag.issues.length} flagged` : 'No flags'}</span></div></div></div><div class="section-title">DIAGNOSTICS <span>${diag.confidence === 'medium' ? 'FILE CLUE' : 'REVIEW'}</span></div><div class="findings">${flagged ? diag.issues.map(i => `<div class="finding">${icon('alert', 15)} ${esc(i)}</div>`).join('') : `<div class="positive">${icon('check', 16)} No automated heuristics flagged this entry.</div>`}${diag.clues.map(c => `<small>${esc(c)}</small>`).join('')}</div><div class="metadata-block"><span>File</span><div title="${esc(item.file_path)}">${esc(item.file_path || 'No file path available')}</div><span>Agent GUID</span><div>${esc(item.guid || 'None')}</div></div><div class="section-title">LOOKUP & EVIDENCE</div><div class="lookup-controls"><select id="order"><option value="aired" ${state.providerOrder === 'aired' ? 'selected' : ''}>Aired order</option><option value="dvd" ${state.providerOrder === 'dvd' ? 'selected' : ''}>DVD order</option></select><button class="btn btn-secondary" data-action="lookup" ${state.busy ? 'disabled' : ''}>${icon('spark', 16)} Find matches</button></div><div class="provider-caption">TVmaze · Wikidata ${state.status?.tmdb_enabled ? '· TMDB' : '· TMDB token optional'} · Plex match candidates below</div>${candidates.length ? `<div class="candidate-list">${candidates.slice(0, 6).map((c, i) => `<div class="candidate"><div class="candidate-row"><div class="candidate-thumb">${c.poster_url ? `<img src="${esc(c.poster_url)}" loading="lazy" alt="Candidate poster"/>` : icon('film', 19)}</div><div class="candidate-info"><b>${esc(c.title)}</b><span>${esc(c.provider)} · ${esc(c.year)} · ${Math.round(c.score * 100)}% heuristic score</span><a href="${esc(c.source_url)}" target="_blank" rel="noopener noreferrer">View source ${icon('external', 13)}</a></div></div><div class="candidate-buttons"><button data-choice="title:${i}">Use title</button>${item.type === 'Movie' && c.year && /^\d{4}$/.test(String(c.year)) ? `<button data-choice="year:${i}" title="Stage the provider's release year for review">Use year</button>` : ''}${c.poster_url ? `<button data-choice="poster:${i}">Use poster</button>` : ''}</div></div>`).join('')}</div>` : `<div class="lookup-empty">${esc(state.lookupMessage || 'Look up external evidence before approving a correction.')}</div>`}<div class="mini-action-row"><button data-action="plex-matches">${icon('search', 14)} Plex matches</button><button data-action="plex-posters">${icon('film', 14)} Existing posters</button></div>${state.matchMessage ? `<div class="lookup-empty">${esc(state.matchMessage)}</div>` : ''}${state.matches.length ? `<div class="options-list">${state.matches.slice(0, 10).map((m, i) => `<div class="option"><span>${esc(m.name || m.title || m.guid || 'Candidate')} ${esc(m.year || '')}<small>${esc(m.guid || '')}</small></span><button data-match="${i}" ${!m.guid ? 'disabled' : ''}>Use match</button></div>`).join('')}</div>` : ''}${state.posterMessage ? `<div class="lookup-empty">${esc(state.posterMessage)}</div>` : ''}${state.posters.length ? `<div class="poster-grid">${state.posters.slice(0, 30).map((m, i) => `<div class="poster-option ${d.poster_key === m.ratingKey ? 'poster-staged' : ''}"><img src="/api/poster-choice/${encodeURIComponent(item.plex_id)}/${i}" loading="lazy" alt="Poster option ${i + 1}"/><small>${esc(m.provider || 'Plex')} ${m.selected ? '· Current' : ''}${d.poster_key === m.ratingKey ? ' · Staged' : ''}</small><button data-poster="${i}" ${m.selected ? 'title="Already selected"' : ''}>${d.poster_key === m.ratingKey ? 'Staged' : m.selected ? 'Keep current' : 'Use poster'}</button></div>`).join('')}</div>` : ''}<div class="section-title">PROPOSED CHANGES <span>EDITABLE</span></div><div class="edit-group"><label for="proposed-title">Plex title</label><input id="proposed-title" placeholder="Leave empty to keep current title" value="${esc(d.title || '')}"/><div class="helper">${diag.proposed_title ? `Suggested from path: <button class="text-link" data-action="use-file-title">${esc(diag.proposed_title)}</button>` : 'A blank field means no change.'}</div>${item.collections ? `<div class="prefix-row">${item.collections.split('|').map(c => c.trim()).filter(Boolean).slice(0, 3).map(c => `<button data-prefix="${esc(c)}">Prefix: ${esc(c)}</button>`).join('')}</div>` : ''}</div><div class="edit-group"><label for="proposed-year">Release year <span class="optional">(Plex metadata)</span></label><input id="proposed-year" type="number" min="1888" max="2100" step="1" placeholder="Leave unchanged" value="${esc(d.year || '')}"/><div class="helper">Currently: <strong>${esc(item.year || 'Unknown')}</strong>. ${esc(diag.year_evidence?.explanation || 'Use a reliable metadata source to verify this year.')}</div>${d.year_sources?.length ? `<div class="helper"><strong>Provider-supported proposal:</strong> ${d.year_sources.map(src => `<a href="${esc(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.provider)}: ${esc(src.title)} (${esc(src.year)})</a>`).join(' · ')} — Pending approval</div>` : ''}${diag.year_evidence?.proposed_year ? `<button class="year-quickfix" data-action="use-year">${icon('bolt', 15)} Use ${esc(diag.year_evidence.proposed_year)} from ${diag.year_evidence.folder_year && diag.year_evidence.filename_year ? 'folder + filename' : diag.year_evidence.filename_year ? 'filename' : 'folder'}</button>` : ''}<div class="helper">Staged changes require approval. Release year does not automatically rename your files.</div></div><div class="edit-group"><label for="proposed-file">Filename <span class="optional">(basename only)</span></label><input id="proposed-file" placeholder="Leave unchanged" value="${esc(d.filename || '')}"/><div class="helper">${diag.proposed_filename ? `Suggested: <button class="text-link" data-action="use-file-name">${esc(diag.proposed_filename)}</button> · ` : ''}<button class="text-link" data-action="suggest-filename">Build from proposed title</button></div><div class="helper">${state.status?.ssh_connected && !state.status?.media_roots?.length ? '<strong class="rename-warning">Renames are disabled: no Allowed media directories configured.</strong> <button class="text-link" data-action="configure-roots">Configure now</button>' : `Allowed: ${esc((state.status?.media_roots || []).join(' · ') || 'Set MEDIA_ROOTS locally or connect via SSH')}`}</div><div class="helper"><button class="text-link" data-action="test-rename">Check filename rename (no changes)</button></div>${state.renamePreflight ? `<div class="rename-check">${esc(state.renamePreflight)}</div>` : ''}</div>${item.type === 'Movie' || item.type === 'Show' ? `<div class="edit-group"><label for="proposed-folder">Containing ${item.type === 'Show' ? 'series' : 'movie'} folder <span class="optional">(basename only)</span></label><input id="proposed-folder" placeholder="Leave unchanged" value="${esc(d.folder || '')}"/><div class="helper">Current folder: <strong>${esc((item.folder_path || item.file_path?.slice(0, item.file_path.lastIndexOf('/'))) || 'No unambiguous folder recorded')}</strong></div><div class="folder-quick-actions"><button class="btn btn-subtle small" data-action="suggest-folder">${icon('bolt', 14)} Fix folder name/year</button>${item.type === 'Movie' ? `<button class="btn btn-subtle small" data-action="suggest-both">${icon('layers', 14)} Fix folder + filename</button>` : ''}</div><div class="helper"><button class="text-link" data-action="test-folder">Check folder rename (preview only)</button> · Moves all contents, including subtitles${item.type === 'Show' ? ' and season directories' : ''}. Plex scan requires confirmation afterward.</div>${state.folderPreflight ? `<div class="rename-check">${esc(state.folderPreflight)}</div>` : ''}</div>` : ''}<div class="edit-group"><label for="proposed-poster">Poster URL</label><input id="proposed-poster" placeholder="Choose from provider above" value="${esc(d.poster_url || '')}"/><div class="helper">Only verified TMDB / TVmaze HTTPS image URLs are accepted.</div>${d.poster_url || d.poster_key ? `<div class="poster-compare"><figure><img src="/api/poster/${encodeURIComponent(item.plex_id)}" alt="Current Plex poster"/><figcaption>Currently in Plex</figcaption></figure><figure>${d.poster_url || state.posters.some(p => p.ratingKey === d.poster_key) ? `<img src="${esc(d.poster_url || '/api/poster-choice/' + encodeURIComponent(item.plex_id) + '/' + state.posters.findIndex(p => p.ratingKey === d.poster_key))}" alt="Proposed poster"/>` : '<div class="poster-unloaded">Click Existing posters to load the selected image.</div>'}<figcaption>${d.poster_key && !state.posters.some(p => p.ratingKey === d.poster_key) ? 'Chosen Plex artwork — click Existing posters to preview' : 'Proposed replacement'}</figcaption></figure></div>` : ''}</div>${d.poster_key || d.match_guid ? `<div class="staged-extra">${d.poster_key ? 'Plex poster selected · ' : ''}${d.match_guid ? 'Metadata rematch selected' : ''}</div>` : ''}<div class="inspector-actions"><button class="btn btn-plain" data-action="save">Save proposal</button><button class="btn ${d.approved ? 'btn-approved' : 'btn-primary'}" data-action="approve">${icon(d.approved ? 'check' : 'lock', 16)} ${d.approved ? 'Approved' : 'Approve changes'}</button></div><div class="safety-note">${icon('alert', 15)} File/folder edits can trigger Plex rescans; poster and match operations may require manual reversal.</div></div></aside>`;
}
function logPanel() { return `<div class="modal-backdrop" data-dismiss="1"><div class="modal" role="dialog" aria-modal="true" aria-label="Change history"><div class="modal-top"><h2>Change history</h2><button data-action="hide-logs" class="icon-button">${icon('x')}</button></div><p>Applied changes from this workspace. Plex poster and agent rematches are not automatically reversible.</p><div class="log-list">${state.logs.length ? state.logs.map(x => `<div class="log-entry"><b>#${esc(x.plex_id)} · ${esc((x.changes || []).join(', '))}</b><small>${esc(x.at)}</small><div>${x.status === 'failed' ? `<strong class="rename-warning">FAILED: ${esc(x.error || 'Unknown error')}</strong><small>Attempted: ${esc((x.attempted || []).join(', '))}. Review Plex before retrying.</small>` : `${esc(x.old_title || '')} ${x.new_title && x.old_title !== x.new_title ? ' → ' + esc(x.new_title) : ''}`}</div>${x.old_year && x.old_year !== x.new_year ? `<small>Release year: ${esc(x.old_year)} → ${esc(x.new_year)}</small>` : ''}${x.old_folder && x.old_folder !== x.new_folder ? `<small>Folder: ${esc(x.old_folder)} → ${esc(x.new_folder)}</small>` : ''}${x.old_file && x.old_file !== x.new_file ? `<small>File: ${esc(x.old_file)} → ${esc(x.new_file)}</small>` : ''}</div>`).join('') : 'No changes applied yet.'}</div></div></div>`; }
const renameKey = (id, file) => id + '\u0000' + file;
const scannedPath = (x) => x.data?.scan_path || x.data?.new_file || '';
const fileFolder = (path) => path.slice(0, path.lastIndexOf('/'));
function markFolderScanned(sectionId, folder) {
    for (const x of renamedFiles()) {
        if (String(x.data.section_id) === sectionId && (x.data.scan_folder || fileFolder(x.data.new_file)) === folder)
            state.scannedRenames.add(renameKey(x.id, scannedPath(x)));
    }
}
const renamedFiles = () => state.lastApplyResults.filter(x => x.ok && (x.data?.changes?.includes('filename') || x.data?.changes?.includes('folder')) && (x.data?.scan_path || x.data?.new_file));
function applyResultsPanel() {
    const total = state.lastApplyResults.length;
    const errors = state.lastApplyResults.filter(x => !x.ok);
    const renamed = renamedFiles();
    const pending = renamed.filter(x => !state.scannedRenames.has(renameKey(x.id, scannedPath(x))));
    const report = state.scanReport;
    return `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true" aria-label="Apply results"><div class="modal-top"><h2>Changes applied: ${total - errors.length}/${total}</h2><button class="icon-button" data-action="hide-apply-results" ${state.scanBusy ? 'disabled' : ''}>${icon('x')}</button></div>
 <p>File renames affect files on disk. A Plex scan may still be needed. Scans run asynchronously; inspect affected media after Plex finishes.</p>
 ${renamed.length > 1 ? `<div class="batch-scan-actions"><div><b>${renamed.length} successful file/folder renames</b><small>${state.scannedRenames.size} renamed items covered by requested scans. Same-folder requests are deduplicated.</small></div><button class="btn btn-primary" data-action="scan-all-renames" ${state.scanBusy || pending.length === 0 ? 'disabled' : ''}>${icon('refresh', 15)} ${state.scanBusy ? 'Requesting scans…' : pending.length === 0 ? 'All scans requested' : 'Request Plex folder scan for all'}</button></div>` : ''}
 ${report ? `<div class="scan-summary" role="status"><b>${report.queued_folders} folder scan${report.queued_folders === 1 ? '' : 's'} queued${report.failed_folders ? ' · ' + report.failed_folders + ' failed' : ''}</b><small>Requested for ${report.requested_files} renamed item${report.requested_files === 1 ? '' : 's'} across ${report.unique_folders} unique folders. Plex completion is not yet confirmed.</small>${report.results.map((r) => `<div class="scan-folder ${r.ok ? '' : 'scan-failed'}">${r.ok ? 'Queued' : 'Failed'} · ${esc(r.folder)}${r.ok ? '' : ` — ${esc(r.error || 'Unknown error')}`}</div>`).join('')}</div>` : ''}
 <div class="log-list">${state.lastApplyResults.map(x => `<div class="log-entry"><b>#${esc(x.id)} · ${x.ok ? 'Success' : 'Failed'}</b>${x.ok ? `<div>${esc((x.data?.changes || []).join(', '))}</div>${(x.data?.changes?.includes('filename') || x.data?.changes?.includes('folder')) && (x.data?.new_file || x.data?.new_folder) ? `<small>${x.data.new_folder ? `Folder: ${esc(x.data.old_folder)} → ${esc(x.data.new_folder)} · ` : ''}${x.data.old_file && x.data.old_file !== x.data.new_file ? `File: ${esc(x.data.old_file)} → ${esc(x.data.new_file)}` : ''}</small><button class="btn btn-subtle small" data-scan="${esc(x.id)}" data-file="${esc(scannedPath(x))}" ${state.scanBusy || state.scannedRenames.has(renameKey(x.id, scannedPath(x))) ? 'disabled' : ''}>${state.scannedRenames.has(renameKey(x.id, scannedPath(x))) ? 'Scan requested' : 'Request Plex folder scan'}</button>` : ''}` : `<div class="rename-warning">${esc(x.error || 'Unknown error')}</div>`}</div>`).join('')}</div><div class="ssh-footer"><button class="btn btn-primary" data-action="hide-apply-results" ${state.scanBusy ? 'disabled' : ''}>Close</button></div></div></div>`;
}
function yearBatchPanel() {
    const report = state.yearBatchReport;
    if (!report)
        return '';
    const verified = report.verified || [];
    const one = (x, status) => {
        const sources = (x.sources || []).filter((src) => src?.provider);
        const sourceLinks = sources.length ? `<div class="year-sources">${sources.map((src) => {
            const name = `${src.provider}: ${src.title || 'Unknown'} (${src.year || '—'})`;
            const href = String(src.url || '');
            return /^https:\/\//i.test(href) ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(name)}</a>` : `<span>${esc(name)}</span>`;
        }).join(' · ')}</div>` : '';
        const desc = status === 'staged' ? `Proposed: ${Object.entries(x.suggested || {}).filter(([key]) => (x.changes || []).includes(key)).map(([key, val]) => `${key === 'year' ? 'Plex year' : key === 'folder' ? 'Folder name' : 'Filename'} → ${val}`).join(' · ')}` : x.reason || 'Requires review';
        return `<div class="log-entry year-review-item"><b>${esc(x.title || 'Untitled')} <small>#${esc(x.id)}</small></b><div class="year-review-status">${status === 'staged' ? 'Pending approval' : status === 'verified' ? 'Already aligned' : 'Needs review'}</div><div class="year-values"><span>Plex: <strong>${esc(x.plex_year || '—')}</strong></span><span>Filename: <strong>${esc(x.filename_year || '—')}</strong></span><span>Folder: <strong>${esc(x.folder_year || '—')}</strong></span><span>Provider: <strong>${esc(x.provider_year || 'Unconfirmed')}</strong></span></div><div class="year-review-desc">${esc(desc)}</div>${sourceLinks}${x.notes?.length ? `<small>${esc(x.notes.join(' · '))}</small>` : ''}${x.provider_errors?.length ? `<small>${esc(x.provider_errors.join(' · '))}</small>` : ''}${status === 'staged' ? `<button type="button" class="btn btn-subtle small year-review-open" data-review-year="${esc(x.id)}">Open proposal</button>` : ''}</div>`;
    };
    return `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true" aria-label="Release-year verification"><div class="modal-top"><h2>Provider year review: ${report.staged.length} pending</h2><button class="icon-button" data-action="hide-year-report" aria-label="Close">${icon('x')}</button></div><p>${report.staged.length} proposed · ${verified.length} already aligned · ${report.skipped.length} need review. Changes to Plex, filenames, and movie folders are proposals only until individually approved and applied. Existing filenames/titles are preserved except for the year token.</p><div class="log-list">${report.staged.map((x) => one(x, 'staged')).join('')}${verified.map((x) => one(x, 'verified')).join('')}${report.skipped.map((x) => one(x, 'skipped')).join('')}</div><div class="ssh-footer">${report.staged.length ? `<button class="btn btn-primary" data-action="review-year-proposals">Review ${report.staged.length} proposal${report.staged.length === 1 ? '' : 's'}</button>` : `<button class="btn btn-primary" data-action="hide-year-report">Close report</button>`}</div></div></div>`;
}
function connectPanel() {
    if (!state.showConnect)
        return '';
    const c = state.connectionDraft || state.status?.ssh_config;
    return `<div class="modal-backdrop"><div class="modal ssh-modal"><div class="modal-top"><h2>Connect to Plex via SSH</h2><button class="icon-button" data-action="ssh-close" aria-label="Close">${icon('x')}</button></div><p>Curator runs on this computer. OpenSSH forwards the Plex API and executes read-only database queries remotely. Key-based SSH access required.</p><form id="ssh-form"><div class="ssh-fields"><label>Server IP or hostname<input name="host" required placeholder="192.168.1.101" value="${esc(c?.host || '192.168.1.101')}"/></label><label>SSH user<input name="user" required value="${esc(c?.user || 'root')}"/></label><label>SSH port<input name="port" type="number" min="1" max="65535" value="${esc(c?.port || 22)}"/></label><label>Remote database path<input name="db" required value="${esc(c?.db || '/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db')}"/></label><label>Allowed media directories <small>(required to rename; one path per line)</small><textarea name="media_roots" rows="3" placeholder="/mnt/media/Movies&#10;/mnt/media/TV">${esc((c?.media_roots || []).join('\n'))}</textarea></label></div><div class="ssh-footer"><div>File renames are disabled unless you list the Plex server media directories above. Use a shared parent directory such as /mnt/media/Movies.</div><button type="submit" class="btn btn-primary" ${state.busy ? 'disabled' : ''}>Connect &amp; load library</button></div></form></div></div>`;
}
function render() { app.innerHTML = `<div class="shell ${state.selected ? 'editor-open' : ''} ${state.mobileNavOpen ? 'nav-open' : ''}"><header class="mobile-bar"><button type="button" class="mobile-menu-button" data-action="toggle-mobile-nav" aria-label="Open library navigation" aria-expanded="${state.mobileNavOpen}">${icon('layers', 20)}</button><div class="mobile-brand">PLEX<span>CURATOR</span></div><div class="mobile-connection ${state.status?.ssh_connected ? 'is-connected' : ''}" title="${state.status?.ssh_connected ? 'SSH connected' : 'Not SSH connected'}"><span class="dot"></span>${state.status?.ssh_connected ? 'Connected' : 'Offline'}</div></header>${sidebar()}<button type="button" class="nav-backdrop" data-action="toggle-mobile-nav" aria-label="Close navigation"></button>${main()}<button type="button" class="inspector-backdrop" data-action="close" aria-label="Close media editor"></button>${inspector()}</div>${state.showLog ? logPanel() : ''}${state.showApplyResults ? applyResultsPanel() : ''}${state.yearBatchReport ? yearBatchPanel() : ''}${connectPanel()}<input id="csv-file" type="file" accept=".csv,text/csv" hidden/><div id="toast" class="toast ${state.toast ? 'show' : ''}">${esc(state.toast)}</div><div id="busy" class="busy ${state.busy ? 'visible' : ''}"><div class="spinner"></div><span>${esc(state.yearBatchProgress || 'Working...')}</span></div>`; }
async function refresh(keepSelection = true) {
    const p = new URLSearchParams({ q: state.query, type: state.nav, flagged: String(state.flagged), offset: String(state.offset), limit: String(state.limit) });
    const [list, status] = await Promise.all([api('/items?' + p), api('/status')]);
    state.items = list.items;
    state.stats = list.stats;
    state.total = list.total;
    state.status = status;
    if (keepSelection && !state.items.some(x => x.plex_id === state.selected)) {
        state.selected = '';
        state.matches = [];
        state.posters = [];
    }
    render();
}
function editDraft() { return { title: (document.querySelector('#proposed-title')?.value || '').trim(), year: (document.querySelector('#proposed-year')?.value || '').trim(), filename: (document.querySelector('#proposed-file')?.value || '').trim(), folder: (document.querySelector('#proposed-folder')?.value || '').trim(), poster_url: (document.querySelector('#proposed-poster')?.value || '').trim() }; }
async function saveDraft(approve) {
    const item = selected();
    if (!item)
        return;
    const draft = editDraft();
    const payload = { id: item.plex_id, ...draft, ...(approve !== undefined ? { approved: approve } : {}) };
    const changed = await api('/decision', 'POST', payload);
    const idx = state.items.findIndex(x => x.plex_id === item.plex_id);
    if (idx >= 0)
        state.items[idx] = changed;
    render();
    toast(changed.decision.approved ? 'Changes approved. Ready to apply.' : 'Proposal saved — not yet applied.');
}
async function lookup(id) { const res = await api('/lookup', 'POST', { id, order: state.providerOrder, provider: 'all' }); state.lookups.set(id, res.results); state.lookupMessage = res.errors.join(' · ') || (res.results.length ? '' : 'No provider match at the selected episode order.'); return res; }
async function action(name) {
    try {
        if (name === 'toggle-mobile-nav') {
            state.mobileNavOpen = !state.mobileNavOpen;
            render();
            if (state.mobileNavOpen)
                document.querySelector('.nav-close')?.focus();
            return;
        }
        if (name === 'connect-ssh') {
            state.showConnect = true;
            render();
            return;
        }
        if (name === 'configure-roots') {
            const it = selected();
            const cfg = state.status?.ssh_config;
            if (!cfg)
                return toast('Connect over SSH to configure allowed media roots.');
            const dir = it?.file_path?.split('/').slice(0, -1).join('/');
            state.connectionDraft = { ...cfg, media_roots: cfg.media_roots.length ? cfg.media_roots : (dir ? [dir] : []) };
            state.showConnect = true;
            render();
            return;
        }
        if (name === 'hide-year-report') {
            state.yearBatchReport = null;
            render();
            return;
        }
        if (name === 'review-year-proposals') {
            state.yearBatchReport = null;
            state.nav = 'proposals';
            state.flagged = false;
            state.query = '';
            state.offset = 0;
            state.selectedIds.clear();
            state.selected = '';
            state.mobileNavOpen = false;
            await refresh();
            if (state.items.length) {
                state.selected = state.items[0].plex_id;
                render();
            }
            return;
        }
        if (name === 'hide-apply-results') {
            if (state.scanBusy)
                return;
            state.showApplyResults = false;
            render();
            return;
        }
        if (name === 'scan-all-renames') {
            const pending = renamedFiles().filter(x => !state.scannedRenames.has(renameKey(x.id, scannedPath(x))));
            if (pending.length < 1 || state.scanBusy)
                return;
            if (!window.confirm(`Request Plex scans for folders containing ${pending.length} successful media changes? Plex may re-identify media. No full-library scan will be requested.`))
                return;
            state.scanBusy = true;
            render();
            try {
                const report = await api('/scan-renames', 'POST', { renames: pending.map(x => ({ id: x.id, new_file: scannedPath(x) })) });
                state.scanReport = report;
                for (const result of report.results) {
                    if (result.ok) {
                        for (let i = 0; i < result.ids.length; i++)
                            state.scannedRenames.add(renameKey(result.ids[i], result.files[i]));
                    }
                }
                toast(report.message);
            }
            catch (e) {
                toast(e.message);
            }
            finally {
                state.scanBusy = false;
                render();
            }
            return;
        }
        if (name === 'ssh-close') {
            state.showConnect = false;
            render();
            return;
        }
        if (name === 'disconnect-ssh') {
            await api('/disconnect', 'POST', {});
            state.selected = '';
            state.selectedIds.clear();
            await refresh();
            toast('SSH connection closed.');
            return;
        }
        if (name === 'import') {
            document.querySelector('#csv-file')?.click();
            return;
        }
        if (name === 'db') {
            state.busy = true;
            render();
            const result = await api('/load-db', 'POST', {});
            state.offset = 0;
            state.selected = '';
            state.selectedIds.clear();
            await refresh();
            toast(`Loaded ${n(result.count)} Plex DB records in read-only mode.`);
            return;
        }
        if (name === 'export') {
            window.location.assign('/api/export');
            return;
        }
        if (name === 'flagged') {
            state.flagged = !state.flagged;
            state.offset = 0;
            await refresh();
            return;
        }
        if (name === 'next' || name === 'prev') {
            state.offset = Math.max(0, state.offset + (name === 'next' ? state.limit : -state.limit));
            await refresh();
            return;
        }
        if (name === 'close') {
            state.selected = '';
            render();
            return;
        }
        if (name === 'use-file-name') {
            const it = selected();
            const el = document.querySelector('#proposed-file');
            if (it && el)
                el.value = it.diagnostic.proposed_filename;
            state.renamePreflight = '';
            return;
        }
        if (name === 'suggest-filename') {
            const it = selected();
            if (!it)
                return;
            const title = document.querySelector('#proposed-title')?.value || it.plex_title;
            const year = document.querySelector('#proposed-year')?.value || it.year || '';
            const r = await api('/suggest-filename', 'POST', { id: it.plex_id, title, year: String(year) });
            const el = document.querySelector('#proposed-file');
            if (el)
                el.value = r.filename || '';
            state.renamePreflight = '';
            toast(r.filename ? 'Filename suggested. Test, then approve and Apply.' : 'No filename change needed, or episode numbering is unavailable.');
            return;
        }
        if (name === 'suggest-folder' || name === 'suggest-both') {
            const it = selected();
            if (!it)
                return;
            const title = document.querySelector('#proposed-title')?.value || it.plex_title;
            const year = document.querySelector('#proposed-year')?.value || it.year || '';
            const r = await api('/suggest-folder', 'POST', { id: it.plex_id, title, year: String(year) });
            const el = document.querySelector('#proposed-folder');
            if (el)
                el.value = r.folder || '';
            if (name === 'suggest-both') {
                const fr = await api('/suggest-filename', 'POST', { id: it.plex_id, title, year: String(year) });
                const fe = document.querySelector('#proposed-file');
                if (fe)
                    fe.value = fr.filename || '';
            }
            state.folderPreflight = '';
            state.renamePreflight = '';
            toast(r.folder ? 'Folder proposal generated. Preview, approve, then apply.' : 'Folder already matches the proposed name/year, or its path is unavailable.');
            return;
        }
        if (name === 'test-folder') {
            const it = selected();
            if (!it)
                return;
            const folder = document.querySelector('#proposed-folder')?.value.trim() || '';
            const filename = document.querySelector('#proposed-file')?.value.trim() || '';
            if (!folder) {
                toast('Enter a proposed folder name first.');
                return;
            }
            const drafts = editDraft();
            try {
                const r = await api('/validate-folder', 'POST', { id: it.plex_id, folder, filename });
                state.folderPreflight = `READY (preview only): ${r.old_folder} → ${r.new_folder}${filename ? ` · File: ${r.old_file} → ${r.new_file}` : ''}. ${r.message}`;
            }
            catch (e) {
                state.folderPreflight = `BLOCKED: ${e.message}`;
            }
            render();
            for (const [selector, value] of Object.entries({ '#proposed-title': drafts.title, '#proposed-year': drafts.year, '#proposed-file': drafts.filename, '#proposed-folder': drafts.folder, '#proposed-poster': drafts.poster_url })) {
                const input = document.querySelector(selector);
                if (input && value !== undefined)
                    input.value = value;
            }
            return;
        }
        if (name === 'test-rename') {
            const it = selected();
            const filename = document.querySelector('#proposed-file')?.value.trim();
            if (!it || !filename) {
                toast('Enter a proposed filename first.');
                return;
            }
            try {
                const r = await api('/validate-filename', 'POST', { id: it.plex_id, filename });
                state.renamePreflight = `READY: ${r.old_file} → ${r.new_file}. ${r.message}`;
            }
            catch (err) {
                state.renamePreflight = `BLOCKED: ${err.message}`;
            }
            const drafts = editDraft();
            render();
            Object.entries({ '#proposed-title': drafts.title, '#proposed-year': drafts.year, '#proposed-file': drafts.filename, '#proposed-folder': drafts.folder, '#proposed-poster': drafts.poster_url }).forEach(([selector, value]) => { const input = document.querySelector(selector); if (input && value !== undefined)
                input.value = value; });
            return;
        }
        if (name === 'use-year') {
            const it = selected();
            const el = document.querySelector('#proposed-year');
            if (it && el) {
                el.value = it.diagnostic.year_evidence.proposed_year || '';
                toast('Release-year correction staged in the form. Save or approve to continue.');
            }
            return;
        }
        if (name === 'batch-years') {
            const ids = (state.selectedIds.size ? [...state.selectedIds] : state.items.filter(i => i.type === 'Movie' || i.type === 'Show').map(i => i.plex_id)).slice(0, 250);
            if (!ids.length) {
                toast('Select movies or TV shows to verify release years.');
                return;
            }
            if (!window.confirm(`Look up metadata providers for ${ids.length} selected/visible record(s) and stage supported year corrections? Conflicting or uncertain matches will be skipped. Nothing will be applied to Plex.`))
                return;
            state.busy = true;
            state.yearBatchReport = null;
            const staged = [], skipped = [], verified = [];
            try {
                for (let x = 0; x < ids.length; x += 5) {
                    state.yearBatchProgress = `Checking provider years ${Math.min(x + 5, ids.length)}/${ids.length}...`;
                    render();
                    const batch = ids.slice(x, x + 5);
                    try {
                        const result = await api('/stage-years', 'POST', { ids: batch });
                        staged.push(...result.staged);
                        skipped.push(...result.skipped);
                        verified.push(...(result.verified || []));
                    }
                    catch (error) {
                        skipped.push(...batch.map(id => ({ id, reason: error.message })));
                    }
                }
            }
            finally {
                state.busy = false;
                state.yearBatchProgress = '';
            }
            state.yearBatchReport = { staged, skipped, verified };
            await refresh();
            toast(`Provider verification: ${staged.length} pending approval; ${verified.length} aligned; ${skipped.length} need review.`);
            return;
        }
        if (name === 'use-file-title') {
            const it = selected();
            const input = document.querySelector('#proposed-title');
            if (it && input)
                input.value = it.diagnostic.proposed_title;
            return;
        }
        if (name === 'lookup') {
            const it = selected();
            if (!it)
                return;
            state.busy = true;
            render();
            await lookup(it.plex_id);
            state.busy = false;
            render();
            toast('Provider lookup completed. Compare evidence before approving.');
            return;
        }
        if (name === 'save') {
            await saveDraft();
            return;
        }
        if (name === 'approve') {
            const it = selected();
            if (!it)
                return;
            const draft = editDraft();
            const prepared = Object.values(draft).some(Boolean) || it.decision.match_guid || it.decision.poster_key;
            if (!prepared) {
                toast('Propose a specific change first.');
                return;
            }
            if (it.decision.approved) {
                await api('/decision', 'POST', { id: it.plex_id, approved: false });
                await refresh();
                toast('Approval revoked.');
                return;
            }
            await api('/decision', 'POST', { id: it.plex_id, ...draft });
            await api('/decision', 'POST', { id: it.plex_id, approved: true });
            await refresh();
            toast('Changes approved. They are not applied until you press Apply approved.');
            return;
        }
        if (name === 'plex-matches') {
            const it = selected();
            if (!it)
                return;
            state.matches = await api('/plex-matches/' + it.plex_id);
            state.matchMessage = state.matches.length ? '' : 'Plex returned no matches. Try a corrected title, agent settings, or native Plex Fix Match.';
            render();
            return;
        }
        if (name === 'plex-posters') {
            const it = selected();
            if (!it)
                return;
            state.posters = await api('/plex-posters/' + it.plex_id);
            state.posterMessage = state.posters.length ? '' : 'Plex returned no artwork choices for this item.';
            render();
            return;
        }
        if (name === 'logs') {
            state.mobileNavOpen = false;
            state.logs = await api('/logs');
            state.showLog = true;
            render();
            return;
        }
        if (name === 'hide-logs') {
            state.showLog = false;
            render();
            return;
        }
        if (name === 'batch-lookup') {
            const ids = state.selectedIds.size ? [...state.selectedIds].slice(0, 20) : state.items.filter(i => i.diagnostic.issues.length > 0).slice(0, 12).map(i => i.plex_id);
            if (!ids.length) {
                toast('Select some records to analyze.');
                return;
            }
            state.busy = true;
            render();
            let found = 0;
            for (const id of ids) {
                try {
                    const r = await lookup(id);
                    found += r.results.length;
                }
                catch (e) { /* leave the record review-only on provider failure */ }
                await new Promise(r => setTimeout(r, 550));
            }
            state.busy = false;
            render();
            toast(`Looked up ${ids.length} records; found ${found} provider candidates.`);
            return;
        }
        if (name === 'apply') {
            const ids = state.selectedIds.size ? [...state.selectedIds] : state.items.filter(i => i.decision.approved).map(i => i.plex_id);
            const approved = ids.filter(id => state.items.some(x => x.plex_id === id && x.decision.approved));
            if (!approved.length) {
                toast('No approved records in the current view. Approve changes first.');
                return;
            }
            const folderCount = approved.filter(id => state.items.some(x => x.plex_id === id && Boolean(x.decision.folder))).length;
            if (!window.confirm(`Apply approved changes to ${approved.length} selected / visible Plex record(s)?${folderCount ? `\n\n${folderCount} approved FOLDER RENAME(s) will move every file and subdirectory within each folder. Confirm the preview and request a Plex scan afterward.` : ''}\n\nThese are live changes. Continue?`))
                return;
            state.busy = true;
            render();
            const results = [];
            for (let x = 0; x < approved.length; x += 20) {
                const reply = await api('/apply', 'POST', { ids: approved.slice(x, x + 20), confirm: 'APPLY' });
                results.push(...reply.results);
            }
            state.busy = false;
            state.selectedIds.clear();
            state.lastApplyResults = results;
            state.scanReport = null;
            state.scannedRenames.clear();
            state.showApplyResults = true;
            await refresh();
            toast(`Completed ${results.filter(x => x.ok).length}/${results.length}; see detailed results.`);
            return;
        }
    }
    catch (e) {
        state.busy = false;
        render();
        toast(e.message);
    }
}
app.addEventListener('submit', async (event) => {
    const target = event.target;
    if (target.id !== 'ssh-form')
        return;
    event.preventDefault();
    const data = new FormData(target);
    const body = { host: String(data.get('host') || '').trim(), user: String(data.get('user') || '').trim(), port: Number(data.get('port') || 22), db: String(data.get('db') || '').trim(), media_roots: String(data.get('media_roots') || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean) };
    try {
        state.connectionDraft = body;
        state.busy = true;
        render();
        const response = await api('/connect', 'POST', body);
        state.busy = false;
        state.showConnect = false;
        state.connectionDraft = null;
        state.offset = 0;
        state.selected = '';
        state.renamePreflight = '';
        state.selectedIds.clear();
        await refresh();
        toast(`Connected to Plex over SSH. Loaded ${n(response.count)} records.${response.token_found ? '' : ' Set PLEX_TOKEN locally for Plex metadata edits.'}`);
    }
    catch (e) {
        state.busy = false;
        render();
        toast(e.message);
    }
});
app.addEventListener('click', async (event) => {
    const target = event.target;
    const review = target.closest('[data-review-year]');
    if (review) {
        const id = review.dataset.reviewYear || '';
        if (!/^\d+$/.test(id))
            return;
        state.yearBatchReport = null;
        state.nav = 'proposals';
        state.flagged = false;
        state.query = '#' + id;
        state.offset = 0;
        state.selectedIds.clear();
        state.selected = id;
        state.mobileNavOpen = false;
        try {
            await refresh();
            if (!state.items.some(item => item.plex_id === id))
                toast('Proposal no longer staged. Refresh the database and run verification again.');
        }
        catch (error) {
            toast(error.message);
        }
        return;
    }
    const link = target.closest('[data-action]');
    if (link) {
        event.preventDefault();
        await action(link.dataset.action || '');
        return;
    }
    const scan = target.closest('[data-scan]');
    if (scan) {
        const id = scan.dataset.scan || '';
        const new_file = scan.dataset.file || '';
        if (state.scanBusy || state.scannedRenames.has(renameKey(id, new_file)))
            return;
        if (!window.confirm(`Request a Plex library scan for the folder containing ${new_file}? This may cause Plex to re-identify media; check its metadata afterward.`))
            return;
        state.scanBusy = true;
        render();
        try {
            const r = await api('/scan-rename', 'POST', { id, new_file });
            markFolderScanned(r.section_id, r.folder);
            toast(r.message);
        }
        catch (e) {
            toast(e.message);
        }
        finally {
            state.scanBusy = false;
            render();
        }
        return;
    }
    const prefix = target.closest('[data-prefix]');
    if (prefix) {
        const it = selected();
        const input = document.querySelector('#proposed-title');
        if (it && input) {
            const base = input.value || it.plex_title;
            const name = prefix.dataset.prefix || '';
            if (name && !base.toLowerCase().startsWith(name.toLowerCase() + ':'))
                input.value = name + ': ' + base;
            toast('Collection prefix staged for review.');
        }
        return;
    }
    const nav = target.closest('[data-nav]');
    if (nav) {
        state.nav = nav.dataset.nav || 'all';
        state.mobileNavOpen = false;
        state.offset = 0;
        await refresh();
        return;
    }
    const item = target.closest('[data-id]');
    if (item && !target.closest('[data-select]')) {
        state.mobileNavOpen = false;
        state.selected = item.dataset.id || '';
        state.renamePreflight = '';
        state.folderPreflight = '';
        state.matches = [];
        state.posters = [];
        state.lookupMessage = '';
        state.matchMessage = '';
        state.posterMessage = '';
        const chosen = selected();
        if (chosen?.decision.poster_key && state.status?.plex_token) {
            try {
                state.posters = await api('/plex-posters/' + chosen.plex_id);
            }
            catch (e) {
                state.posterMessage = e.message;
            }
        }
        render();
        return;
    }
    const choice = target.closest('[data-choice]');
    if (choice) {
        const it = selected();
        if (!it)
            return;
        const [field, index] = choice.dataset.choice.split(':');
        const c = (state.lookups.get(it.plex_id) || it.candidates || [])[Number(index)];
        if (!c)
            return;
        // Existing collection prefixes are deliberately preserved when candidate is their suffix.
        let value = c.title;
        if (field === 'title' && it.plex_title.includes(':') && it.plex_title.toLowerCase().endsWith(c.title.toLowerCase()))
            value = it.plex_title;
        if (field === 'title') {
            const input = document.querySelector('#proposed-title');
            if (input)
                input.value = value;
        }
        else if (field === 'year') {
            const input = document.querySelector('#proposed-year');
            if (input && /^\d{4}$/.test(c.year))
                input.value = c.year;
        }
        else {
            const input = document.querySelector('#proposed-poster');
            if (input)
                input.value = c.poster_url;
            await saveDraft();
            toast('Poster choice saved for preview — approval still required.');
            return;
        }
        toast(`${field === 'title' ? 'Title' : field === 'year' ? 'Year' : 'Poster'} staged — save and approve separately.`);
        return;
    }
    const match = target.closest('[data-match]');
    if (match) {
        const it = selected();
        if (!it)
            return;
        const m = state.matches[Number(match.dataset.match)];
        if (!m?.guid)
            return;
        await api('/decision', 'POST', { id: it.plex_id, match_guid: m.guid });
        await refresh();
        toast('Plex rematch proposed. Approval required.');
        return;
    }
    const poster = target.closest('[data-poster]');
    if (poster) {
        const it = selected();
        if (!it)
            return;
        const p = state.posters[Number(poster.dataset.poster)];
        if (!p?.ratingKey)
            return;
        await api('/decision', 'POST', { id: it.plex_id, poster_key: p.ratingKey });
        await refresh();
        toast('Poster staged (not applied). Check the image comparison and approve.');
        return;
    }
});
app.addEventListener('change', async (event) => {
    const t = event.target;
    if (t.id === 'csv-file') {
        const el = t;
        const file = el.files?.[0];
        if (!file)
            return;
        try {
            state.busy = true;
            render();
            const csv = await file.text();
            const result = await api('/import', 'POST', { csv });
            state.offset = 0;
            state.selected = '';
            state.selectedIds.clear();
            state.busy = false;
            await refresh();
            toast(`Imported ${n(result.count)} CSV records.`);
        }
        catch (e) {
            state.busy = false;
            render();
            toast(e.message);
        }
        return;
    }
    if (t.id === 'order') {
        state.providerOrder = t.value;
        return;
    }
    if (t.id === 'pick-all') {
        const checked = t.checked;
        state.items.forEach(x => checked ? state.selectedIds.add(x.plex_id) : state.selectedIds.delete(x.plex_id));
        render();
        return;
    }
    const pick = t.closest('[data-select]');
    if (pick) {
        const id = pick.dataset.select || '';
        if (pick.checked)
            state.selectedIds.add(id);
        else
            state.selectedIds.delete(id);
        document.querySelector('.selected-counter').textContent = `${state.selectedIds.size} selected`;
        return;
    }
});
let debounce;
app.addEventListener('input', ev => { const t = ev.target; if (t.id === 'search') {
    clearTimeout(debounce);
    state.query = t.value;
    debounce = window.setTimeout(async () => { state.offset = 0; await refresh(); document.querySelector('#search')?.focus(); }, 320);
} });
refresh().catch(e => { render(); toast('Backend offline. Start: python3 backend/server.py'); });
// Keyboard behavior shared by the desktop inventory and the mobile drawer/editor.
document.addEventListener('keydown', async (event) => {
    if (event.key === 'Escape') {
        if (state.showConnect) {
            state.showConnect = false;
            render();
            return;
        }
        if (state.yearBatchReport) {
            state.yearBatchReport = null;
            render();
            return;
        }
        if (state.showApplyResults && !state.scanBusy) {
            state.showApplyResults = false;
            render();
            return;
        }
        if (state.showLog) {
            state.showLog = false;
            render();
            return;
        }
        if (state.mobileNavOpen) {
            state.mobileNavOpen = false;
            render();
            return;
        }
        if (state.selected) {
            state.selected = '';
            render();
            return;
        }
    }
    const row = event.target.closest('.media-row[data-id]');
    if (row && (event.key === 'Enter' || event.key === ' ') && !(event.target.closest('input,button,a'))) {
        event.preventDefault();
        row.click();
    }
});
