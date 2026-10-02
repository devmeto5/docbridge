import os
import socket
import subprocess
import sys
import unittest


class IsolationTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'linux', 'Linux container isolation test')
    def test_worker_cannot_open_network_socket(self):
        code = '''
from docbridge.worker import restrict_linux
import socket
restrict_linux()
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        socket.socket(family, socket.SOCK_STREAM)
    except PermissionError:
        continue
    raise SystemExit("Network socket was allowed")
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM):
    pass
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
