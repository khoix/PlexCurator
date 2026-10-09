"""Portable OpenSSH transport for a locally running Plex Curator backend."""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

BRIDGE_SCRIPT = Path(__file__).with_name('remote_bridge.py')
DEFAULT_DB = '/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db'


class SSHTransport:
    def __init__(self):
        self.lock = threading.RLock()
        self.config = None
        self.tunnel = None
        self.local_port = None
        self.token = ''

    @staticmethod
    def validate(raw):
        if not isinstance(raw, dict):
            raise ValueError('SSH settings must be an object')
        host = str(raw.get('host', '')).strip()
        user = str(raw.get('user', '')).strip()
        port = int(raw.get('port', 22))
        db = str(raw.get('db', DEFAULT_DB)).strip()
        roots = raw.get('media_roots', [])
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}', host):
            raise ValueError('Invalid SSH hostname or IP')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,62}', user):
            raise ValueError('Invalid SSH username')
        if port < 1 or port > 65535:
            raise ValueError('Invalid SSH port')
        if not db.startswith('/') or '\x00' in db or '\n' in db:
            raise ValueError('Remote Plex database must have an absolute Unix path')
        if not isinstance(roots, list) or len(roots) > 20 or any(not isinstance(r, str) or not r.startswith('/') or '\x00' in r or '\n' in r for r in roots):
            raise ValueError('Media roots must be absolute paths on the Plex host')
        return {'host': host, 'user': user, 'port': port, 'db': db, 'media_roots': roots}

    def ssh_base(self, cfg):
        if not shutil.which('ssh'):
            raise ValueError('OpenSSH client not found in PATH. Install OpenSSH or enable Windows OpenSSH Client.')
        return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                '-o', 'StrictHostKeyChecking=accept-new', '-p', str(cfg['port']),
                '-l', cfg['user']]

    def call(self, request, cfg=None):
        cfg = cfg or self.config
        if not cfg:
            raise ValueError('Connect to the Plex server through SSH first')
        payload = base64.urlsafe_b64encode(json.dumps(request).encode('utf-8')).decode('ascii')
        # The command argument is generated entirely by the app, not by a user.
        cmd = self.ssh_base(cfg) + [cfg['host'], 'python3 - ' + payload]
        try:
            run = subprocess.run(cmd, input=BRIDGE_SCRIPT.read_bytes(), capture_output=True, timeout=65)
        except subprocess.TimeoutExpired:
            raise ValueError('SSH operation timed out')
        except OSError as e:
            raise ValueError('Unable to execute SSH: ' + str(e))
        raw = run.stdout.decode('utf-8', 'replace').strip()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            err = run.stderr.decode('utf-8', 'replace').strip()[-600:]
            raise ValueError('SSH remote operation failed. ' + (err or raw[-250:]))
        if not result.get('ok'):
            raise ValueError(result.get('error', 'Remote Plex operation failed'))
        return result['result']

    @staticmethod
    def choose_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', 0))
            return sock.getsockname()[1]

    def connect(self, raw):
        cfg = self.validate(raw)
        with self.lock:
            self.close()
            # Connection and data read are independent of Plex API forwarding.
            snapshot = self.call({'op':'load', 'db':cfg['db']}, cfg)
            token = self.call({'op':'token', 'db':cfg['db']}, cfg)['token']
            port = self.choose_port()
            args = self.ssh_base(cfg)
            args[1:1] = ['-N', '-o', 'ExitOnForwardFailure=yes',
                         '-L', f'127.0.0.1:{port}:127.0.0.1:32400']
            args += [cfg['host']]
            proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
            try:
                for _ in range(35):
                    if proc.poll() is not None:
                        detail = proc.stderr.read().decode('utf-8', 'replace')[-500:]
                        raise ValueError('SSH tunnel could not start: ' + detail)
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.3):
                            break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise ValueError('SSH tunnel did not become reachable')
            except Exception:
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired: proc.kill()
                raise
            self.config = cfg
            self.token = token
            self.local_port = port
            self.tunnel = proc
            return snapshot['rows']

    def close(self):
        if self.tunnel is not None and self.tunnel.poll() is None:
            self.tunnel.terminate()
            try: self.tunnel.wait(timeout=2)
            except subprocess.TimeoutExpired: self.tunnel.kill()
        if self.tunnel and self.tunnel.stderr:
            self.tunnel.stderr.close()
        self.tunnel = None
        self.config = None
        self.local_port = None
        self.token = ''

    @property
    def connected(self):
        return bool(self.config and self.tunnel and self.tunnel.poll() is None)

    def rename(self, old, newname, apply):
        if not self.connected:
            raise ValueError('SSH tunnel is disconnected; reconnect before writing')
        return self.call({'op': 'rename' if apply else 'validate_rename',
                          'source': old, 'new_name': newname,
                          'roots': self.config['media_roots']})

    def rename_bundle(self, file_path, folder_path, filename, folder_name, apply=False):
        if not self.connected:
            raise ValueError('SSH tunnel is disconnected; reconnect before writing')
        return self.call({'op':'rename_bundle' if apply else 'validate_bundle',
                          'source':file_path or '', 'folder_source':folder_path or '',
                          'new_name':filename or '', 'new_folder':folder_name or '',
                          'roots':self.config['media_roots']})
