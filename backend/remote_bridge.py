#!/usr/bin/env python3
"""Executed on the remote Plex machine via `ssh python3 - <base64-json>`.

Requires only Python 3.10+, reads Plex SQLite in read-only mode, and offers
explicitly guarded basename-only renames. No code is installed remotely.
"""
import base64
import ctypes
import errno
import sys
import json
import os
import pathlib
import sqlite3
import stat
import sys
import urllib.parse
import xml.etree.ElementTree as ET


def rows_from_db(db_path):
    path = pathlib.Path(db_path)
    if not path.is_file():
        raise ValueError('Plex database not found or not readable: ' + str(path))
    uri = 'file:' + urllib.parse.quote(str(path)) + '?mode=ro'
    source = sqlite3.connect(uri, uri=True, timeout=15)
    dest = sqlite3.connect(':memory:')
    try:
        source.backup(dest)
        dest.row_factory = sqlite3.Row
        sql = '''SELECT m.id AS plex_id,
             CASE m.metadata_type WHEN 1 THEN 'Movie' WHEN 2 THEN 'Show' WHEN 4 THEN 'Episode' END AS type,
             ls.name AS library, m.library_section_id AS library_section_id, COALESCE(show.title,'') AS series_title, CASE WHEN m.metadata_type=2 THEN m.id ELSE show.id END AS series_id,
             m.title AS plex_title, m.original_title, m.year, m.guid,
             m.user_thumb_url AS poster_override, mp.file AS file_path,
             SUBSTR(m.summary,1,300) AS summary_excerpt,
             m."index" AS episode_number, season."index" AS season_number
             FROM metadata_items m
             LEFT JOIN library_sections ls ON ls.id=m.library_section_id
             LEFT JOIN metadata_items season ON season.id=m.parent_id AND m.metadata_type=4
             LEFT JOIN metadata_items show ON show.id=season.parent_id AND m.metadata_type=4
             LEFT JOIN media_items mi ON mi.id=(SELECT MIN(x.id) FROM media_items x WHERE x.metadata_item_id=m.id)
             LEFT JOIN media_parts mp ON mp.id=(SELECT MIN(x.id) FROM media_parts x WHERE x.media_item_id=mi.id)
             WHERE m.metadata_type IN (1,2,4) AND m.deleted_at IS NULL
             ORDER BY ls.name, m.title'''
        rows = [dict(x) for x in dest.execute(sql)]
        tables = {x[0] for x in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if {'tags', 'taggings'} <= tables:
            try:
                collections = {str(x[0]): x[1] for x in dest.execute('''
                    SELECT g.metadata_item_id, GROUP_CONCAT(t.tag, ' | ')
                    FROM taggings g JOIN tags t ON t.id=g.tag_id
                    WHERE t.tag_type=2 GROUP BY g.metadata_item_id''')}
                for row in rows:
                    row['collections'] = collections.get(str(row['plex_id']), '')
            except sqlite3.OperationalError:
                pass
        return rows
    finally:
        source.close()
        dest.close()


def rename_without_overwrite(src, target):
    """Atomic same-directory move; never overwrite another file.

    Linux/Fedora renameat2(RENAME_NOREPLACE) handles filesystems that cannot
    create hardlinks (e.g., some FUSE/SMB mounts). Hardlink/unlink is a guarded
    fallback when renameat2 is genuinely unsupported.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        func = libc.renameat2
    except AttributeError:
        func = None
    if func is not None:
        func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                         ctypes.c_char_p, ctypes.c_uint]
        func.restype = ctypes.c_int
        res = func(-100, os.fsencode(src), -100, os.fsencode(target), 1)
        if res == 0:
            return 'atomic-rename'
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ValueError('Destination already exists; will not overwrite: ' + str(target))
        if code not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise OSError(code, os.strerror(code), str(src))
    # If the platform/filesystem lacks NOREPLACE support, try the no-clobber
    # hardlink method. This preserves the original if linking is rejected.
    try:
        os.link(src, target, follow_symlinks=False)
    except OSError as exc:
        raise ValueError('Filesystem cannot perform a protected rename: ' +
                         f'{exc}. No files were changed.') from exc
    try:
        os.unlink(src)
    except OSError:
        os.unlink(target)
        raise
    return 'hardlink-fallback'


def media_rename(args, apply):
    source_name, new_name = args.get('source', ''), args.get('new_name', '')
    roots = args.get('roots', [])
    if not isinstance(roots, list) or not roots:
        raise ValueError('Filename renames disabled: add the media library directory to Allowed media directories under Connect via SSH, then reconnect')
    if (not isinstance(source_name, str) or not isinstance(new_name, str) or
        not new_name or new_name in ('.', '..') or any(c in new_name for c in ('/', '\\', '\x00'))):
        raise ValueError('Filename must be a basename without directory separators')
    src = pathlib.Path(source_name).resolve(strict=True)
    allowed = [pathlib.Path(r).resolve(strict=True) for r in roots]
    if not any(src.is_relative_to(root) for root in allowed):
        raise ValueError('Source is outside the permitted media roots')
    metadata = src.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError('Source must be a regular file')
    target = src.with_name(new_name)
    if target.suffix.lower() != src.suffix.lower():
        raise ValueError('File extension cannot change')
    if str(target) == str(src):
        raise ValueError('New filename is identical to the original')
    if target.exists() or target.is_symlink():
        raise ValueError('Target file already exists')
    if apply:
        method = rename_without_overwrite(src, target)
    else:
        method = 'preview'
        if not os.access(src.parent, os.W_OK | os.X_OK):
            raise ValueError('SSH account cannot write to directory: ' + str(src.parent))
    return {'old_file': str(src), 'new_file': str(target), 'applied': apply, 'method':method}


def folder_and_file_rename(args, apply):
    """One guarded request for a movie file and/or its containing folder.

    Rename file first, then folder; rollback the filename if the folder move fails.
    No recursive walk, shell command, merge, or overwrite is ever performed.
    """
    source_dir = args.get('folder_source', '')
    new_dirname = args.get('new_folder', '')
    source_file = args.get('source', '')
    new_filename = args.get('new_name', '')
    roots = args.get('roots', [])
    if not new_dirname and not new_filename:
        raise ValueError('No file or folder rename requested')
    if not isinstance(roots, list) or not roots:
        raise ValueError('Renames require Allowed media directories')
    allowed = [pathlib.Path(root).resolve(strict=True) for root in roots]
    if not source_dir and source_file:
        source_dir = str(pathlib.Path(source_file).parent)
    if not source_dir:
        raise ValueError('No media directory recorded for this item')
    folder = pathlib.Path(source_dir).resolve(strict=True)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError('Source folder is not a real directory')
    if not any(folder.is_relative_to(root) and folder != root for root in allowed):
        raise ValueError('Folder must be BELOW an allowed media root; cannot rename the root itself')
    if new_dirname:
        if (not isinstance(new_dirname, str) or new_dirname in ('.','..') or
            len(new_dirname) > 240 or any(c in new_dirname for c in ('/', '\\', '\x00')) or
            any(ord(c)<32 for c in new_dirname) or new_dirname.endswith((' ', '.'))):
            raise ValueError('New folder name must be a safe basename (no path separators)')
        dest_dir = folder.with_name(new_dirname)
        if dest_dir == folder:
            raise ValueError('Folder name is unchanged')
        if dest_dir.exists() or dest_dir.is_symlink():
            raise ValueError('Destination folder already exists; refusing to merge or overwrite')
        if not os.access(folder.parent, os.W_OK | os.X_OK):
            raise ValueError('SSH user cannot rename folders in this parent directory')
        # No hardlink fallback is possible/safe for directories.
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            if not hasattr(libc, 'renameat2'):
                raise ValueError('Protected directory rename unavailable on this Plex filesystem')
        except OSError as error:
            raise ValueError(f'Protected directory rename unavailable: {error}')
    else:
        dest_dir = folder

    src = None; dest_file = None
    if new_filename:
        if not source_file:
            raise ValueError('Cannot rename a file without its original path')
        src = pathlib.Path(source_file).resolve(strict=True)
        if src.parent != folder:
            raise ValueError('File is not directly inside the folder being renamed')
        pre = media_rename({'source':str(src),'new_name':new_filename,'roots':roots},False)
        dest_file = pathlib.Path(pre['new_file'])
    elif source_file:
        src = pathlib.Path(source_file).resolve(strict=True)
        if not src.is_file() or not src.is_relative_to(folder):
            raise ValueError('Original media file is not inside the folder')
        dest_file = src

    final_file = str(dest_dir / dest_file.relative_to(folder)) if dest_file is not None else ''
    result = {'old_file':str(src) if src else '', 'new_file':final_file,
              'old_folder':str(folder), 'new_folder':str(dest_dir),
              'applied':apply, 'method':'preview',
              'scan_path':final_file or str(dest_dir),
              'scan_folder':str(folder.parent if new_dirname else (dest_file.parent if dest_file else dest_dir))}
    if not apply: return result
    file_moved = False
    try:
        if new_filename:
            file_op = media_rename({'source':str(src),'new_name':new_filename,'roots':roots}, True)
            file_moved = True
            result['method'] = file_op['method']
        if new_dirname:
            # rename_without_overwrite checks EEXIST atomically. Explicitly disallow hardlink fallback.
            libc=ctypes.CDLL(None, use_errno=True)
            func=libc.renameat2
            func.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
            func.restype=ctypes.c_int
            if func(-100,os.fsencode(folder),-100,os.fsencode(dest_dir),1) != 0:
                code=ctypes.get_errno()
                raise OSError(code,os.strerror(code),str(folder))
            result['method'] = 'atomic-folder-rename' if not new_filename else 'atomic-file-and-folder-rename'
        result['applied']=True
        return result
    except Exception as err:
        if file_moved:
            try:
                media_rename({'source':str(dest_file),'new_name':src.name,'roots':roots}, True)
            except Exception as rollback_err:
                raise ValueError(f'Folder move failed: {err}; filename rollback ALSO FAILED: {rollback_err}. Inspect paths manually.') from err
        raise


def perform(args):
    op = args.get('op')
    if op == 'load':
        return {'rows': rows_from_db(args['db'])}
    if op == 'token':
        path = pathlib.Path(args['db']).parent.parent.parent / 'Preferences.xml'
        try:
            return {'token': ET.parse(path).getroot().attrib.get('PlexOnlineToken', '')}
        except (OSError, ET.ParseError):
            return {'token': ''}
    if op == 'validate_rename':
        return media_rename(args, False)
    if op == 'rename':
        return media_rename(args, True)
    if op == 'validate_bundle':
        return folder_and_file_rename(args, False)
    if op == 'rename_bundle':
        return folder_and_file_rename(args, True)
    raise ValueError('Unsupported bridge operation')


def main():
    try:
        args = json.loads(base64.urlsafe_b64decode(sys.argv[1]).decode('utf-8'))
        print(json.dumps({'ok': True, 'result': perform(args)}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        sys.exit(1)

if __name__ == '__main__':
    main()
