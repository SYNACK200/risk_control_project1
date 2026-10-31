"""Read-only root authentication. No credential arguments or disk storage."""
import json
import struct
import sys


def receive_secret(stream):
    header = stream.read(4)
    if len(header) != 4:
        raise ValueError()
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= 65536:
        raise ValueError()
    data = bytearray(stream.read(size))
    try:
        if len(data) != size or stream.read(1):
            raise ValueError()
        obj = json.loads(data.decode('utf-8', errors='strict'))
        if not isinstance(obj, dict) or set(obj) != {'password'}:
            raise ValueError()
        secret = obj['password']
        if not isinstance(secret, str) or not secret:
            raise ValueError()
        if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in secret):
            raise ValueError()
        secret.encode('utf-8', errors='strict')
        return secret
    finally:
        data[:] = b'\0' * len(data)


def dependencies():
    from importlib.metadata import version
    import re
    import pymysql
    from pymysql import _auth
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    if sys.version_info[:2] not in ((3, 11), (3, 12)):
        raise ValueError()
    for name, low, high in [('PyMySQL', (1, 1, 1), (2, 0, 0)),
                            ('cryptography', (41, 0, 0), (50, 0, 0))]:
        v = version(name)
        if not re.fullmatch(r'\d+\.\d+\.\d+', v) or not low <= tuple(map(int, v.split('.'))) < high:
            raise ValueError()
    if not _auth._have_cryptography or not callable(_auth.sha2_rsa_encrypt) or not callable(_auth.caching_sha2_password_auth):
        raise ValueError()
    if not default_backend().rsa_padding_supported(padding.OAEP(
            mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)):
        raise ValueError()
    return pymysql


def main():
    secret = None
    try:
        mode = sys.argv[1]
        if mode == 'transport-test':
            # Fixed synthetic fixture ONLY. Never use this mode for a real password.
            secret = receive_secret(sys.stdin.buffer)
            if secret != 'Synthetic-\u6f22\u5b57-\U0001f600-!"\\$` ':
                raise ValueError()
            print('TRANSPORT PASS')
            return 0
        if mode != 'authenticate':
            raise ValueError()
        try:
            driver = dependencies()
        except Exception:
            print('AUTHENTICATION FAIL: DEPENDENCY_UNAVAILABLE')
            return 1
        try:
            secret = receive_secret(sys.stdin.buffer)
        except Exception:
            print('AUTHENTICATION FAIL: INPUT_REJECTED')
            return 1
        try:
            with driver.connect(host='127.0.0.1', port=3307, user='root',
                                password=secret.encode('utf-8'), charset='utf8mb4',
                                local_infile=False, autocommit=True, connect_timeout=5,
                                read_timeout=10, write_timeout=10) as conn:
                secret = None
                with conn.cursor() as cur:
                    cur.execute('SELECT VERSION(), @@port, @@datadir, CURRENT_USER()')
                    version, port, directory, user = cur.fetchone()
                    if not (version.startswith('8.4.') and port == 3307 and
                            directory.replace('\\', '/').rstrip('/').lower() ==
                            'd:/riskcontroldemo/mysql84/data' and user == 'root@localhost'):
                        raise ValueError()
            print('AUTHENTICATION PASS')
            return 0
        except Exception as error:
            rejected = error.args and type(error.args[0]) is int and error.args[0] == 1045
            print('AUTHENTICATION FAIL: ' + ('AUTHENTICATION_REJECTED' if rejected else 'CONNECTION_OR_TARGET_FAILURE'))
            return 1
    except (Exception, KeyboardInterrupt):
        print('AUTHENTICATION FAIL: INPUT_REJECTED')
        return 1
    finally:
        secret = None


if __name__ == '__main__':
    sys.exit(main())
