"""DA-01 core. Interactive credentials arrive only in framed anonymous stdin."""
import json
import re
import struct
import sys
from pathlib import Path
from authenticate_pipe import dependencies


class SafeFailure(RuntimeError):
    pass


def emit(message):
    # Protocol messages contain prompts/categories only, never credentials.
    print(json.dumps(message, ensure_ascii=True), flush=True)


def read_response(stream):
    header = stream.read(4)
    if len(header) != 4:
        raise SafeFailure('INPUT_EOF')
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= 65536:
        raise SafeFailure('INPUT_REJECTED')
    data = bytearray(stream.read(size))
    try:
        if len(data) != size:
            raise SafeFailure('INPUT_EOF')
        obj = json.loads(data.decode('utf-8', errors='strict'))
        if not isinstance(obj, dict) or set(obj) != {'value'} or not isinstance(obj['value'], str):
            raise SafeFailure('INPUT_REJECTED')
        return obj['value']
    except (ValueError, UnicodeError):
        raise SafeFailure('INPUT_REJECTED') from None
    finally:
        data[:] = b'\0' * len(data)


def request_secret(account, phase, minimum=1, reader=None):
    emit({'type': 'secret', 'account': account, 'phase': phase})
    value = (reader or read_response)(sys.stdin.buffer)
    if not value:
        raise SafeFailure('EMPTY_INPUT')
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise SafeFailure('CONTROL_CHARACTER')
    if len(value) < minimum:
        raise SafeFailure('TOO_SHORT')
    try:
        value.encode('utf-8', errors='strict')
    except UnicodeError:
        raise SafeFailure('INPUT_REJECTED') from None
    return value


def collect_credentials(existing, request=request_secret):
    collected = {}
    first = second = None
    try:
        for user, _ in pairs:
            if existing[user]:
                continue
            first = request(user, 'new', 16)
            second = request(user, 'confirm', 16)
            if first != second:
                raise SafeFailure('CONFIRMATION_MISMATCH')
            if first in collected.values():
                raise SafeFailure('REUSED_CREDENTIAL')
            collected[user] = first
            first = second = None
        return collected
    except BaseException:
        collected.clear()
        first = second = None
        raise

pairs = [("rc_demo_app", "rc_role_app"), ("rc_demo_reader", "rc_role_reader"),
         ("rc_demo_audit_writer", "rc_role_audit_writer")]
expected_dir = "d:/riskcontroldemo/mysql84/data"
folder = str(Path(__file__).resolve().parent)

def connect(user, secret):
    return pymysql.connect(
        host="127.0.0.1", port=3307, user=user, password=secret.encode("utf-8"),
        charset="utf8mb4", autocommit=True, connect_timeout=5,
        read_timeout=15, write_timeout=15, local_infile=False)
def identity(cur):
    cur.execute("SELECT VERSION(), @@port, @@datadir")
    version, port, directory = cur.fetchone()
    if not re.match(r"^8[.]4[.]", version) or port != 3307 or \
       directory.replace("\\", "/").rstrip("/").lower() != expected_dir:
        raise RuntimeError("Target mismatch")
    cur.execute("SELECT @@global.mandatory_roles")
    if cur.fetchone()[0] not in ("", "NONE"):
        raise RuntimeError("Unexpected mandatory roles")
def run_sql(cur, filename):
    # Only reviewed single-statement SQL, no stored programs or semicolons in literals.
    text = (Path(folder) / filename).read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("--"))
    for statement in text.split(";"):
        if statement.strip():
            cur.execute(statement)
            if cur.description:
                for row in cur.fetchall():
                    pass
def assert_principal(cur, user, role_account=False, allowed_role=None):
    cur.execute("SELECT host, account_locked FROM mysql.user WHERE user=%s", (user,))
    rows = cur.fetchall()
    if not rows:
        return False
    if rows != (("localhost", "Y" if role_account else "N"),):
        raise RuntimeError("Unexpected principal host/lock")
    cur.execute("SHOW GRANTS FOR %s@'localhost'", (user,))
    grants = [row[0].replace(chr(96), "'") for row in cur.fetchall()]
    allowed = {"GRANT USAGE ON *.* TO " + repr(user) + "@'localhost'"}
    if allowed_role:
        allowed.add("GRANT " + repr(allowed_role) + "@'localhost' TO " +
                    repr(user) + "@'localhost'")
    if any(grant not in allowed for grant in grants):
        raise RuntimeError("Unexpected existing privileges")
    cur.execute("SELECT FROM_USER, FROM_HOST, TO_USER, TO_HOST FROM mysql.role_edges "
                "WHERE FROM_USER=%s OR TO_USER=%s", (user, user))
    for source, shost, target, thost in cur.fetchall():
        permitted = (source == allowed_role and target == user) if not role_account else \
                    any(source == r and target == u for u, r in pairs if r == user)
        if not permitted or shost != "localhost" or thost != "localhost":
            raise RuntimeError("Unexpected role relationship")
    return True
def verify_all(cur):
    for user, role in pairs:
        if not assert_principal(cur, role, True) or \
           not assert_principal(cur, user, allowed_role=role):
            raise RuntimeError("Missing principal")
        cur.execute("SELECT DEFAULT_ROLE_USER, DEFAULT_ROLE_HOST FROM mysql.default_roles "
                    "WHERE USER=%s AND HOST='localhost'", (user,))
        if cur.fetchall() != ((role, "localhost"),):
            raise RuntimeError("Default role mismatch")
        cur.execute("SELECT FROM_USER, FROM_HOST FROM mysql.role_edges "
                    "WHERE TO_USER=%s AND TO_HOST='localhost'", (user,))
        if cur.fetchall() != ((role, "localhost"),):
            raise RuntimeError("Role binding mismatch")
    return True


state = {'stage': 'dependencies', 'writes_started': False}


def prompt(account, phase, minimum=1):
    state['stage'] = 'credential:' + account + ':' + phase
    return request_secret(account, phase, minimum)


def confirm_initialize():
    state['stage'] = 'confirmation'
    emit({'type': 'confirm'})
    if read_response(sys.stdin.buffer) != 'INITIALIZE RC DEMO 3307':
        raise SafeFailure('CONFIRMATION_REQUIRED')


def accept_da01(cur, ask):
    """One admin login plus each runtime login once. SELECT/SHOW only."""
    checks = []
    cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name IN "
                "('rc_demo_biz','rc_demo_report','rc_demo_audit')")
    databases = len(cur.fetchall())
    try:
        run_sql(cur, '03_verify_admin.sql')
        verify_all(cur)
        admin_ok = databases == 3
    except Exception:
        admin_ok = False
    checks.append({'name': 'admin_structure_and_isolation', 'ok': admin_ok,
                   'category': 'PASS' if admin_ok else 'ADMIN_CHECK_FAILED', 'code': None})
    cur.execute("SELECT u.User, u.Host, u.account_locked, u.plugin, "
                "r.DEFAULT_ROLE_USER, r.DEFAULT_ROLE_HOST FROM mysql.user AS u "
                "LEFT JOIN mysql.default_roles AS r ON r.USER=u.User AND r.HOST=u.Host "
                "WHERE u.User IN ('rc_demo_app','rc_demo_reader','rc_demo_audit_writer') "
                "ORDER BY u.User, u.Host, r.DEFAULT_ROLE_USER")
    accounts = list(cur.fetchall())
    expected = {(u, 'localhost', 'N', 'caching_sha2_password', r, 'localhost') for u, r in pairs}
    plugin_ok = len(accounts) == 3 and set(accounts) == expected
    checks.append({'name': 'runtime_metadata', 'ok': plugin_ok,
                   'category': 'PASS' if plugin_ok else 'METADATA_MISMATCH', 'code': None})
    for user, role in pairs:
        secret = None
        try:
            secret = ask(user, 'login')
            state['stage'] = 'runtime:' + user + ':connect'
            with connect(user, secret) as connection:
                secret = None
                with connection.cursor() as runtime:
                    identity(runtime)
                    runtime.execute('SELECT CURRENT_USER(), CURRENT_ROLE()')
                    matched, active = runtime.fetchone()
                    if matched != user + '@localhost':
                        raise SafeFailure('IDENTITY_MISMATCH')
                    if not isinstance(active, str) or active.replace(chr(96), "'") != "'" + role + "'@'localhost'":
                        raise SafeFailure('ROLE_MISMATCH')
            check = {'name': user, 'ok': True, 'category': 'PASS', 'code': None}
        except (EOFError, KeyboardInterrupt):
            raise
        except Exception as error:
            code = error.args[0] if error.args and type(error.args[0]) is int else None
            permitted = {'EMPTY_INPUT', 'CONTROL_CHARACTER', 'TOO_SHORT', 'INPUT_REJECTED',
                         'IDENTITY_MISMATCH', 'ROLE_MISMATCH'}
            category = ('AUTHENTICATION_REJECTED' if code == 1045 else
                        error.args[0] if isinstance(error, SafeFailure) and error.args and
                        error.args[0] in permitted else 'CONNECTION_OR_CHECK_FAILED')
            check = {'name': user, 'ok': False, 'category': category, 'code': code}
        finally:
            secret = None
        checks.append(check)
    return {'type': 'result', 'ok': all(c['ok'] for c in checks), 'mode': 'AcceptDA01',
            'checks': checks, 'runtime_accounts': accounts, 'databases': databases,
            'principals': 6 if admin_ok else 0}


def run(mode, admin='root', apply=False, driver=None, ask=prompt, confirm=confirm_initialize):
    global pymysql
    modes = {'AcceptDA01', 'InspectObjects', 'VerifyAdmin', 'VerifyRuntime', 'AuthenticateRuntime', 'InspectDown', 'Initialize'}
    if mode not in modes or not re.fullmatch(r'[A-Za-z0-9_]+', admin):
        raise SafeFailure('MODE_REJECTED')
    if (mode == 'Initialize') != bool(apply):
        raise SafeFailure('APPLY_REQUIRED')
    if mode == 'AuthenticateRuntime' and admin not in dict(pairs):
        raise SafeFailure('MODE_REJECTED')
    state.update(stage='dependencies', writes_started=False)
    pymysql = driver if driver is not None else dependencies()
    secrets = {}
    secret = None
    try:
        if mode in ('VerifyRuntime', 'AuthenticateRuntime'):
            selected = pairs if mode == 'VerifyRuntime' else [(admin, dict(pairs)[admin])]
            for user, role in selected:
                secret = ask(user, 'login')
                state['stage'] = 'runtime:' + user + ':connect'
                with connect(user, secret) as conn:
                    secret = None
                    with conn.cursor() as cur:
                        state['stage'] = 'runtime:' + user + ':identity'
                        identity(cur)
                        cur.execute('SELECT CURRENT_USER(), CURRENT_ROLE()')
                        matched, active = cur.fetchone()
                        if matched != user + '@localhost':
                            raise SafeFailure('IDENTITY_MISMATCH')
                        if mode == 'VerifyRuntime':
                            state['stage'] = 'runtime:' + user + ':role'
                            if not isinstance(active, str) or active.replace(chr(96), "'") != "'" + role + "'@'localhost'":
                                raise SafeFailure('ROLE_MISMATCH')
                            run_sql(cur, '04_verify_runtime.sql')
            return {'type': 'result', 'ok': True, 'mode': mode}
        secret = ask(admin, 'login')
        state['stage'] = 'administrator:connect'
        with connect(admin, secret) as conn:
            secret = None
            with conn.cursor() as cur:
                state['stage'] = 'target:identity'
                identity(cur)
                cur.execute('SELECT CURRENT_USER()')
                if cur.fetchone()[0] != admin + '@localhost':
                    raise SafeFailure('IDENTITY_MISMATCH')
                if mode == 'AcceptDA01':
                    return accept_da01(cur, ask)
                if mode == 'InspectObjects':
                    cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name IN "
                                "('rc_demo_biz','rc_demo_report','rc_demo_audit')")
                    databases = len(cur.fetchall())
                    cur.execute("SELECT user, host, account_locked FROM mysql.user WHERE user IN "
                                "('rc_role_app','rc_role_reader','rc_role_audit_writer',"
                                "'rc_demo_app','rc_demo_reader','rc_demo_audit_writer')")
                    principals = len(cur.fetchall())
                    # Never select authentication_string or SHOW CREATE USER.
                    cur.execute("SELECT u.User, u.Host, u.account_locked, u.plugin, "
                                "r.DEFAULT_ROLE_USER, r.DEFAULT_ROLE_HOST FROM mysql.user AS u "
                                "LEFT JOIN mysql.default_roles AS r ON r.USER=u.User AND r.HOST=u.Host "
                                "WHERE u.User IN ('rc_demo_app','rc_demo_reader','rc_demo_audit_writer') "
                                "ORDER BY u.User, u.Host, r.DEFAULT_ROLE_USER")
                    accounts = list(cur.fetchall())
                    return {'type': 'result', 'ok': True, 'mode': mode,
                            'databases': databases, 'principals': principals, 'runtime_accounts': accounts}
                if mode == 'InspectDown':
                    run_sql(cur, 'down.sql')
                    return {'type': 'result', 'ok': True, 'mode': mode}
                if mode == 'Initialize':
                    state['stage'] = 'existing:inspect'
                    cur.execute('SELECT @@global.general_log, @@global.slow_query_log')
                    if any(cur.fetchone()):
                        raise SafeFailure('QUERY_LOGGING_ENABLED')
                    existing = {}
                    for user, role in pairs:
                        assert_principal(cur, role, True)
                        existing[user] = assert_principal(cur, user, allowed_role=role)
                    confirm()
                    secrets = collect_credentials(existing, ask)
                    # No DDL before ALL missing-account credentials pass validation.
                    state.update(stage='initialize:sql', writes_started=True)
                    run_sql(cur, '01_databases_roles.sql')
                    for user, role in pairs:
                        if not existing[user]:
                            cur.execute("CREATE USER %s@'localhost' IDENTIFIED WITH caching_sha2_password BY %s",
                                        (user, secrets.pop(user)))
                        cur.execute("GRANT %s@'localhost' TO %s@'localhost'", (role, user))
                        cur.execute("SET DEFAULT ROLE %s@'localhost' TO %s@'localhost'", (role, user))
                    secrets.clear()
                state['stage'] = 'admin:verify'
                run_sql(cur, '03_verify_admin.sql')
                verify_all(cur)
                return {'type': 'result', 'ok': True, 'mode': mode}
    finally:
        secrets.clear()
        secret = None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    try:
        admin = sys.argv[2] if len(sys.argv) > 2 else 'root'
        result = run(mode, admin, apply=sys.argv[3:] == ['--apply'])
        emit(result)
        return 0 if result['ok'] else 1
    except (Exception, KeyboardInterrupt) as error:
        allowed = {'INPUT_EOF', 'INPUT_REJECTED', 'EMPTY_INPUT', 'CONTROL_CHARACTER', 'TOO_SHORT',
                   'CONFIRMATION_MISMATCH', 'REUSED_CREDENTIAL', 'CONFIRMATION_REQUIRED',
                   'MODE_REJECTED', 'APPLY_REQUIRED', 'IDENTITY_MISMATCH', 'ROLE_MISMATCH', 'QUERY_LOGGING_ENABLED'}
        if isinstance(error, KeyboardInterrupt):
            category = 'INPUT_CANCELLED'
        elif isinstance(error, SafeFailure) and error.args and error.args[0] in allowed:
            category = error.args[0]
        else:
            category = ('AUTHENTICATION_REJECTED' if error.args and type(error.args[0]) is int and
                        error.args[0] == 1045 else 'DATABASE_OR_DEPENDENCY_FAILURE')
        code = error.args[0] if error.args and type(error.args[0]) is int else None
        emit({'type': 'result', 'ok': False, 'mode': mode, 'category': category,
              'code': code, 'stage': state['stage'], 'writes_started': state['writes_started']})
        return 1


if __name__ == '__main__':
    sys.exit(main())
