"""LAN server binding and same-origin regression checks."""
import sys, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'backend'))
import server

class TestLANOrigin(unittest.TestCase):
    def test_local_and_lan_origins(self):
        h=object.__new__(server.Handler)
        for hostname in ('127.0.0.1', 'localhost', '192.168.1.54', 'plexcurator.local'):
            h.headers={'Origin':f'http://{hostname}:8765','Host':f'{hostname}:8765'}
            self.assertTrue(h.origin_ok(),hostname)
        h.headers={'Host':'192.168.1.54:8765'}
        self.assertTrue(h.origin_ok())

    def test_cross_origin_and_mismatched_port_rejected(self):
        h=object.__new__(server.Handler)
        for origin in ('http://evil.example:8765','http://192.168.1.54:7777',
                       'null','file:///', 'http://evil.example@192.168.1.54:8765'):
            h.headers={'Origin':origin,'Host':'192.168.1.54:8765'}
            self.assertFalse(h.origin_ok(),origin)

    def test_configurable_binding_default(self):
        with patch('sys.argv',['server.py']), patch.dict(server.os.environ,{'CURATOR_HOST':'0.0.0.0'}), \
             patch.object(server,'ThreadingHTTPServer') as listener, \
             patch.object(server,'plex_token',return_value=''):
            listener.return_value.serve_forever.return_value=None
            server.main()
            self.assertEqual(listener.call_args.args[0],('0.0.0.0',8765))

    def test_loopback_override(self):
        with patch('sys.argv',['server.py','--host','127.0.0.1','--port','9999']), \
             patch.object(server,'ThreadingHTTPServer') as listener, \
             patch.object(server,'plex_token',return_value=''):
            listener.return_value.serve_forever.return_value=None
            server.main()
            self.assertEqual(listener.call_args.args[0],('127.0.0.1',9999))

if __name__=='__main__':unittest.main()
