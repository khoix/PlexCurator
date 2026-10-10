# Plex Curator v0.8 — responsive remote-first metadata editor

Plex Curator is a **Vite + TypeScript web app with a local Python backend**. Run it on **Windows, macOS, or Linux**, and connect to your Plex server over SSH. **Nothing needs to be installed on the Plex machine** beyond its existing SSH service and Python 3.10+.

**Status:** functional alpha. Unit/integration simulations pass; **live Plex API compatibility and SSH access to your particular Plex installation have not yet been verified**. Make a Plex database backup before applying batch edits.


### App icons

The web UI includes a themed golden-chevron and wrench icon: multi-resolution `favicon.ico`, PNG favicons (16×16 and 32×32), and an `apple-touch-icon.png` (180×180). Source assets live under `web/public` for Vite builds; matching prebuilt files live in `web/dist` for the Python standalone server. Both HTML entry points reference these assets, and the Python backend serves them with correct image MIME types. The icon is original artwork inspired by Plex's visual design and is not an official Plex logo.

### Provider-backed year reconciliation

The **Verify & fix years** action compares a verified provider release year separately with the year in Plex metadata, the media filename, and the containing movie directory. It stages whichever of these fields need changing, pending individual approval. The review panel shows the title, Plex ID, all compared years, provider links, and clear reasons for ambiguous or already-correct entries. It does not automatically apply edits.

Only existing unambiguous year tokens are replaced in media basenames; collection prefixes and other title text are retained. Filename/folder operations still require allowed media roots and a live filesystem preflight when applying; stale/CSV-sourced folder updates are not automatically staged. Conflicting provider years, title mismatches, and ambiguous remakes remain review-only. Public providers may impose rate limits.

### Network access (all interfaces)

Plex Curator's Python backend now binds to `0.0.0.0:8765` by default. Open `http://<workstation-ip>:8765` on a phone or computer on your trusted LAN/VPN. The SSH tunnel to Plex remains locally bound on the workstation. The Vite development and preview servers also bind to `0.0.0.0`.

To restrict the app to the workstation, use `./run.sh --host 127.0.0.1` or set `CURATOR_HOST=127.0.0.1` (Windows: `py -3 backend/server.py --host 127.0.0.1`).

**Security:** Curator has no login, and its endpoints can request Plex edits and file renames. Binding to `0.0.0.0` means any host able to reach port 8765 can access it. Firewall the port to trusted devices only; do not port-forward it to the internet. Cross-origin browser writes are blocked, but this is not authentication.

### Provider-verified Fix Years

**Verify & fix years** queries Wikidata for movies, TVmaze for TV shows, and optionally TMDB when `TMDB_READ_TOKEN` is set. Matches are validated by title, not the existing Plex year; movie folder/filename years remain clues only. Ambiguous remakes, conflicting provider results, and low-confidence matches are skipped. Every proposed release year is accompanied by provider links, remains **pending separate approval**, and is not applied until the user explicitly clicks **Apply approved**. Processing shows progress in batches and reports skipped records. Episodes are skipped; no filenames or directories are automatically renamed.

### Discover and review proposals

**Verify & fix years** compares metadata provider release years to Plex metadata, filenames, and movie folders, then saves eligible corrections as *proposals* in `data/decisions.json`. It does not edit Plex or files until each proposal is approved and **Apply approved** is used.

In the results modal, **Open proposal** jumps directly to a selected item. The bottom **Review proposals** action opens the **Proposals** section with its first record selected (or **Close report** if no corrections were staged). The sidebar **Proposals** view persists across page reloads and includes both pending approval and approved-but-unapplied edits, so you can approve and then apply within one view. Items with staged proposals are also visible under the default **Issues only** filter and labeled **Pending approval**.

If the report says **0 pending**, no new proposed corrections were staged: the results were already aligned, conflicted with an existing proposal, or provider identity was uncertain. No Plex edits were performed. An exact Plex ID can be located using a search such as `#12345`.

### v0.8 — desktop, tablet, and mobile web interface

The same Vite web UI now adapts to wide desktop monitors, tablets, and narrow phones (tested at **1600×900**, **820×1000**, **390×844**, and **320×700**). Desktop retains its three-column workspace. On tablets and phones:

- The previously hidden library-navigation links are available in a **menu drawer** with accessible close controls.
- Tapping a media item opens its editor in a **slide-in review panel** (full-screen on phones), so users do not have to scroll past dozens of records to find the editor.
- Inventory cards, batch actions, filename/folder controls, poster choices, and SSH dialogs reflow for smaller screens. Phone forms use touch-sized buttons and inputs that do not cause iOS Safari to zoom.
- Dialogs take the available phone height, respect display safe areas, and allow scrolling to buttons and errors. Escape dismisses desktop overlays and Enter/Space activates a focused inventory record.

The remote SSH/Plex backend and its write safeguards have **not changed**. The Python backend still runs on a Windows/macOS/Linux **computer**, not on a phone. A phone can use the web interface when it can reach the workstation over a trusted LAN/VPN. The Python backend now listens on `0.0.0.0:8765` by default. Keep port 8765 firewalled to trusted clients; do not expose this unauthenticated app to the internet.

**Validation:** 49 existing backend tests and TypeScript type checking pass. Simulated-browser interactive tests of the navigation drawer, selected-item inspector, and SSH dialog pass at the four viewport sizes above without page-level horizontal overflow or JavaScript errors. The UI was tested with simulated API responses from a 5,779-record Plex export; no live Plex edits were performed.

### v0.7 — movie and TV series folder names/years

In the Review Desk, select a **Movie** or **TV Show** (for shows with no automatic diagnostic, turn **Issues only** off). The new **Containing movie folder / Containing series folder** editor provides:

- **Fix folder name/year** — stage a folder basename based on the selected Plex title and proposed year. Existing collection/franchise prefixes in your selected title are preserved.
- **Fix folder + filename** — for movies, stage both renames using the *same* selected title and year, such as `The Matrix (1998)/The Matrix (1998).mkv` → `The Matrix (1999)/The Matrix (1999).mkv`.
- **Check folder rename (preview only)** — verify the current and proposed paths through remote SSH *without changing anything*. This runs the live directory/filename collision, access, root, and ownership checks.
- **Save proposal → Approve changes → Apply approved** — explicit approval is required. The final confirmation warns that moving a directory moves all its contents. Change history records both paths. **Changes applied** offers individual and batch Plex folder scans; for folder renames the scan targets the old/new common parent, so Plex can discover the moved folder.

Folder changes are **not available from a stale/imported CSV**: connect to the server and load a fresh read-only Plex SQLite snapshot. The original SQLite DB is never modified. Folder renames cannot rename an allowed media root, cross into a different media root, or merge with an existing destination. Movies whose folder contains another indexed movie or show are blocked. Whole-series moves use Plex's show/season/episode parent IDs, not approximate show title matching; if the series root can't be identified safely, the field remains unavailable. Filesystem renames run on the remote Plex host over SSH without installing this program there.

**Limitations:** This does not rename individual season directories, update subtitle *filenames*, or guarantee that Plex preserves all metadata after rescanning. Subtitles and sidecars move **with** a renamed folder, but their own basenames remain unchanged. On filesystems that reject no-replace directory renames (including some mounts), the app refuses rather than using a destructive fallback. If a combined operation fails after the filename has moved, the app attempts to roll the filename back; the failure is reported if that cannot be completed. Back up Plex, test one movie first, and keep automatic empty-trash disabled during large renames until you verify your environment.

**Verification:** 49 automated tests pass, including read-only SQL show-parent extraction, combined file/folder rename, collision handling, rollback simulation, episode-path updates, and folder-based scan requests. Browser assets were transpiled from the included Vite/TypeScript source and served locally. **This has not been exercised against the user's live Plex server, SSH filesystem, or Plex scan behavior.**


### Verify & fix titles and filenames

The library toolbar has two additional batch actions: **Verify & fix title** and **Verify & fix filename**. Each queries metadata providers first (TMDB if configured; otherwise Wikidata for movies; TVmaze for shows and episodes). The backend refuses ambiguous remakes, inconsistent provider titles, and unmatched episodes instead of guessing. Movie collection prefixes, such as `Star Wars: ...`, are preserved when intentionally present.

Title actions stage a proposed **Plex metadata title**; filename actions stage a guarded **single-file rename** (movies and numbered episodes only). No filesystem change or Plex edit happens until the user opens the Proposals queue, reviews and approves the proposal, then presses **Apply approved**. Provider attribution is recorded with the proposal. Filename renames still require configured Allowed media directories and a subsequent user-requested Plex scan. Episode lookups use the selected **aired** or **DVD** order from the Review Desk. Confirm TVmaze's ordering against your files before approving, especially for shows with alternate broadcast/DVD orders. Film original release year and alternate/localized titles are not always identical across providers; investigate borderline results before approval.

### Verification previews and proposal removal

**Verify & fix years**, **Verify & fix title**, and **Verify & fix filename** now run provider lookups in preview-only mode. Results display selectable suggestions, which are **not saved** unless the user clicks **Add selected to Proposals**. **Discard / Close** abandons the preview and leaves existing proposals unchanged. Previews expire after 20 minutes and cannot be committed twice; saving rechecks the Plex item identity and proposal state.

The **Proposals** view now offers **Remove** beside each entry and **Remove selected proposals** for explicitly selected rows. The Review Desk also offers **Remove proposal**. Removal deletes only local Curator proposals and their approval status, never Plex metadata or media files; previously applied changes cannot be undone by removing a proposal. Individual approval and **Apply approved** are still required for real changes.

## Architecture

```text
Windows / macOS / Linux workstation
  Browser (Vite UI, served at 0.0.0.0:8765; access via workstation IP)
         ↕
  Local Python 3.10+ backend
         ├── SSH remote command → read-only SQLite snapshot + media file operations
         ├── SSH -L tunnel → Plex API on the remote host (127.0.0.1:32400)
         └── HTTPS → TVmaze / Wikidata / optional TMDB
                                ↕
Plex server (SSH + Python 3.10+ + existing Plex installation)
```

The **SSH client runs on the workstation**, not the Plex server. The SSH tunnel forwards the Plex **API**, not the entire web editor. Binding Curator to all interfaces does not expose its internal Plex SSH tunnel. Read-only database queries and approved filename renames use separately authenticated SSH commands. This is not a browser-only application: browsers cannot directly create SSH sessions or safely mutate remote files.

## Start locally

Requirements on your computer:

- Python **3.10+**
- **OpenSSH client** (`ssh`) available in `PATH` (included or optional on modern Windows/macOS/Linux)
- SSH key-based authentication, or an existing password-free SSH configuration/agent

Node/npm **is not required**. The ZIP contains an already-transpiled Vite browser build.

**Linux/macOS**:

```bash
unzip plex-curator-v0.8-responsive.zip
cd plex-curator
./run.sh
```

**Windows**: Extract ZIP, open PowerShell inside `plex-curator`, then run:

```powershell
py -3 backend/server.py
```

Open **http://127.0.0.1:8765** on the workstation or **http://<workstation-ip>:8765** from a trusted LAN device, then click **Connect via SSH**.

For your Fedora Plex host, defaults in the dialog are:

| Field | Value |
|---|---|
| Host | `192.168.1.101` |
| SSH user | `root` (or a suitably privileged non-root user) |
| SSH port | `22` |
| Remote DB | `/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db` |
| Allowed media roots | **Required for renames** (optional for read-only browsing). List the existing media library parent directories *on Plex*, one per line |

Connecting loads the live catalog in read-only mode and creates an **automatic SSH port forward** to Plex's localhost API. When you close the local backend, SSH forwarding terminates.

### SSH authentication

The editor runs SSH in noninteractive **key/agent mode**, and will not ask for an SSH password inside the browser. On your Linux/macOS workstation, if necessary:

```bash
ssh-keygen -t ed25519
ssh-copy-id root@192.168.1.101
ssh -o BatchMode=yes root@192.168.1.101 'python3 --version'
```

The last command should complete without a password prompt. On Windows, enable **OpenSSH Client**, create an SSH key using `ssh-keygen`, and add its **public** key to the server's `~/.ssh/authorized_keys`. SSH host keys are checked (`StrictHostKeyChecking=accept-new`); modified host keys are rejected. Prefer a dedicated account granted only the required permissions over root.

The remote SSH user must be able to **read Plex's SQLite database and `Preferences.xml`** to discover the token automatically. Alternatively set `PLEX_TOKEN` **on the workstation** before running the backend. **Never paste private SSH keys into the web interface.**

**Important:** no SSH server access means only CSV-import/offline review works. SSH access is required for direct DB reads and file renames.

## Workflow

1. **Connect via SSH** or **Import CSV**. The database is opened read-only and queried from a consistent SQLite snapshot **on the Plex server**. Only the selected metadata rows cross the network, not the entire SQLite file.
2. **Audit** suspicious titles, release tags, year mismatches, episode titles, GUIDs, and artwork clues. Year evidence is displayed separately for filenames and folders, including disagreement warnings.
3. **Look up** TVmaze (including supported alternate/DVD order), Wikidata, and optionally TMDB (`TMDB_READ_TOKEN`). Compare Plex's own match and poster options through the tunneled Plex API.
4. **Propose** Plex title edits, metadata rematches, poster selections, media filename changes, and **movie/TV series folder renames**. **Build from proposed title** uses the proposed title **and proposed year** even if the previous filename looks otherwise clean. Click **Check filename rename** for a read-only remote preflight, which reports path/permission/collision failures before approval.
5. **Quick-fix years:** Select a movie, click **Use [year] from folder/filename**, or select multiple entries and click **Fix years (selected)**. Batch staging only proposes years when *both* folder and filename agree and the title matches. For ambiguous cases, look up a provider and click **Use year**. Proposed years are editable and are **never auto-approved**.
6. **Approve** each proposed edit, then **Apply approved** in controlled batches. Detailed results show success/error per item; every completed action is journaled locally under `data/changes.jsonl`. A filename suggestion **does not** perform a rename until this step.
7. After one successful file or folder rename, the result dialog offers **Request Plex folder scan**. When two or more files are renamed, it also offers **Request Plex folder scan for all**. That queues one partial scan per unique Plex library section and parent folder, reports per-folder failures, and can retry failures without re-queueing successes. This is an explicit opt-in because Plex may interpret renamed media as a new item and can change its identity/metadata. Wait until the Plex scan finishes, verify the affected title in Plex, then **Refresh DB** to inspect the updated state. This only requests/queues a scan; it does not claim the scan finished.

**Collection-aware titles**: `Star Wars: The Empire Strikes Back` is legitimate even if the file or external provider calls it simply `The Empire Strikes Back`. Plex collections, file/folder context, original title, and release year are clues; franchise prefixes are not stripped automatically.

## Change safety and limitations

- **No SQL writes**, local or remote. The remote bridge runs through standard input over SSH, performs a read-only SQLite backup, and queries only selected metadata fields.
- **Metadata changes** go through Plex's authenticated API using an SSH tunnel; their exact compatibility depends on the Plex Media Server version.
- **File/folder renames** run remotely and are **disabled** unless you configure allowed media directories in the SSH connection dialog. The app requires basename-only paths, preserves extensions, rejects out-of-root files and existing destination names, and on Fedora/Linux first uses atomic `renameat2(RENAME_NOREPLACE)` (works on supported filesystems without hard links). A guarded hard-link/unlink fallback is attempted if the first method is unavailable. If neither is supported, the app refuses to rename rather than risk overwriting another file. Filesystems mounted with unusual permissions may also reject the operation. For **movie folders**, you can stage a folder rename or a combined folder + filename rename; the entire directory (including subtitles and sidecars) moves as one. **TV series folders** can be renamed as a whole only when the episode-to-show database relationship unambiguously locates the series root. Single episodes and season folders are not eligible for folder renames. Directory renames prefer Linux `renameat2(RENAME_NOREPLACE)`. If an SMB/NFS/FUSE mount rejects that operation with `EINVAL` or an unsupported-operation error, Curator rechecks the destination before a guarded, same-parent `os.rename` fallback. This fallback cannot guarantee no overwrite in a race with external filesystem activity, so avoid simultaneous changes to the same directory; it does not copy or merge directories.
- **Year edits** use Plex `year.value` and `year.locked=1`; the script verifies that Plex persisted the year. It does not alter `originallyAvailableAt` or automatically rename media files. Release years can differ across release territories, so filename/folder hints are not authoritative.
- **Approval verification**: the item must still have the same imported Plex title, GUID, and path. Changed suggestions clear prior approvals; remote connections must be live before applying.
- No full transaction across Plex API and filesystem, and no reliable automatic rollback of provider rematches/poster changes. **Plex may treat a rename as a new item on the next scan**, possibly losing custom metadata or watched status. Back up Plex first. A scan request is queued asynchronously and may not complete right away. Do not enable auto-empty-trash during a large rename project without understanding the risk; verify a single item first.
- A valid but wrong poster cannot reliably be identified from DB fields alone. Poster changes require human review.
- Ambiguous DVD/air-date episode ordering must be verified before changing titles or media files.
- **Network exposure:** The app binds to `0.0.0.0:8765` by default, with no login portal. Any device able to connect can access its Plex/file-change endpoints. Restrict LAN access with firewall/VPN rules, **never expose it publicly**, and use `--host 127.0.0.1` for local-only use. Same-origin browser checks are not authentication. Avoid running the backend as root.
- Connecting to another server ends the previous tunnel. No automatic reconnection, OS keychain integration, multi-server management, or batch database editing.

## Development

`web/src` contains the full TypeScript/Vite source, and `web/dist` contains the **prebuilt** assets. To build from source (Node and npm required):

```bash
cd web
npm install
npm run build
```

For Vite live reload, run `npm run dev` with the Python backend also running. The frontend proxies `/api` to the local backend.

Tests (no Plex installation required):

```bash
python3 -m unittest discover -s tests -v
```

### Provider / Plex API references

- Plex server data paths: https://support.plex.tv/articles/202915258-where-is-the-plex-media-server-data-directory-located/
- Plex API: https://developer.plex.tv/pms/
- TVmaze: https://www.tvmaze.com/api
- Wikidata API: https://www.mediawiki.org/wiki/Wikibase/API
- TMDB: https://developer.themoviedb.org/docs/authentication-application

### v0.3 changes

- Release-year proposals and a **Use year** button in the inspector, plus provider candidate **Use year** actions.
- **Fix years (selected)** stages high-confidence folder/filename-agreeing movie years across selected records (at most 250 per batch). Uncertain ones are skipped; no edits occur without separate approval and **Apply approved**.
- Direct Plex year edits with stale-year guard, persistence check, and best-effort rollback if a later operation fails.
- CSV export adds `current_year`, `recommended_year`, and `proposed_year`.
- Provider TMDB movie search no longer filters by the possibly incorrect Plex year.

After replacing an older installation, restart the local backend and hard-refresh the browser (Ctrl+Shift+R) to clear cached assets. The previous `data/decisions.json` is preserved, but older approvals are invalidated because the year now participates in the identity check.


### v0.4 — filename rename repair

- The SSH connection form now clearly marks **Allowed media directories** as required for renaming. If none were configured, the inspector offers **Configure now** and proposes the current item's folder. Select a broader parent folder to allow multiple movies or episodes. Reconnect to apply changed permissions.
- **Check filename rename** performs an actual remote read-only preflight: confirms source is a real media file, the path is under an allowed root, the extension is unchanged, and no destination exists.
- Uses `renameat2(RENAME_NOREPLACE)` on Fedora/Linux, not only hard links; retains no-overwrite fallback or fails without changing files.
- **Build from proposed title** honors the proposed year, and works for a tidy filename whose *year* needs correcting.
- Apply results remain visible, including per-file errors, actual old/new paths, and an optional targeted **Request Plex folder scan** action.
- Never performs automatic Plex scans after renaming. The explicit scan action uses the Plex library section ID and renamed file's parent directory, and queues the scan through Plex's API.
- Renaming is still unsafe to combine blindly with multi-version/edition media or changes in episode ordering. Test on one item and keep backups.

### v0.5 — Plex match lookup and poster repairs

- **Plex matches:** Lookups use `GET /library/metadata/{id}/matches?manual=1` first, with a limited `PUT` fallback for PMS variants that reject GET with a 404/405. XML `SearchResult` responses are parsed; if both methods are unsupported the app reports the actual failure instead of showing an empty success.
- **Existing posters:** `GET /library/metadata/{id}/posters` yields `Photo` entries in Plex XML/JSON, **not** the generic `Metadata` list. The editor now reads these correctly, displays up to 30 artwork thumbnails with their selection state, and offers a side-by-side Current vs. Proposed view.
- **Poster image access:** Curator proxies *only* the local Plex metadata image paths through the authenticated SSH-forwarded API. Browser requests never need the Plex token. Browser caches are disabled on previews so applying an image does not leave a stale picture.
- **Applying:** Existing poster selection sends `PUT /library/metadata/{id}/poster?url=...` and checks that Plex subsequently reports the intended key as selected. Remote poster URLs are uploaded, located in the refreshed poster options, selected separately, and checked. If Plex accepts an upload but does not expose it as a poster option, Curator **reports failure/uncertainty**, not success.
- **Rematches:** Applying sends `PUT /library/metadata/{id}/match?guid=...` then checks whether the live GUID changed. Matching may be asynchronous; failure to verify is clearly reported, and the item must be checked in Plex before retrying.
- **Logging:** Requests that may have partially completed are written to `data/changes.jsonl` as `status=failed` with attempted actions and rollback information. Approval is cleared after uncertain partial operations to discourage blind replays.
- These changes were checked against mock PMS HTTP endpoints, including Plex-style XML. **They have not been verified against your live Plex installation.** Differences in Plex version, agent, or library type can still affect the behavior.

**Install safely:** Stop the existing local backend. Make a copy of its `data/` directory first, then extract the ZIP over your existing `plex-curator/` directory. The ZIP intentionally includes only `data/.gitkeep`; it does not overwrite your `decisions.json` or `changes.jsonl`. Restart `./run.sh` (or `py -3 backend/server.py` on Windows), hard-refresh your browser, and test *one* poster and *one* Plex match before making bulk edits.
