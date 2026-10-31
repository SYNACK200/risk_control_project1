"""In-memory SQL sink, never a MySQL connection. Never records password parameters."""
from contextlib import AbstractContextManager

PAIRS = [('rc_demo_app', 'rc_role_app'), ('rc_demo_reader', 'rc_role_reader'),
         ('rc_demo_audit_writer', 'rc_role_audit_writer')]


class FakeDriver:
    def __init__(self, populated=False, port=3307, logs=False):
        self.populated = populated
        self.port = port
        self.logs = logs
        self.roles = {r for u, r in PAIRS} if populated else set()
        self.users = {u for u, r in PAIRS} if populated else set()
        self.bindings = dict(PAIRS) if populated else {}
        self.queries = []
        self.login_users = []

    def connect(self, **kwargs):
        assert kwargs['host'] == '127.0.0.1' and kwargs['port'] == 3307
        assert isinstance(kwargs['password'], bytes)
        self.login_users.append(kwargs['user'])
        return Connection(self, kwargs['user'])


class Connection(AbstractContextManager):
    def __init__(self, db, user): self.db, self.user = db, user
    def __exit__(self, *args): pass
    def cursor(self): return Cursor(self.db, self.user)


class Cursor(AbstractContextManager):
    description = True
    def __init__(self, db, user): self.db, self.user, self.rows = db, user, ()
    def __exit__(self, *args): pass
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0]
    def execute(self, sql, args=None):
        sql = sql.strip()
        self.db.queries.append(sql)  # SQL templates only, never credential parameters.
        self.rows = ((1,),)
        if sql == 'SELECT VERSION(), @@port, @@datadir':
            self.rows = (('8.4.13', self.db.port, 'D:/RiskControlDemo/mysql84/data/'),)
        elif sql == 'SELECT @@global.mandatory_roles': self.rows = (('',),)
        elif sql == 'SELECT CURRENT_USER()': self.rows = ((self.user + '@localhost',),)
        elif sql == 'SELECT CURRENT_USER(), CURRENT_ROLE()':
            active = "'" + self.db.bindings[self.user] + "'@'localhost'" if self.user in self.db.bindings else 'NONE'
            self.rows = ((self.user + '@localhost', active),)
        elif 'SELECT @@global.general_log' in sql: self.rows = ((int(self.db.logs), 0),)
        elif sql.startswith('SELECT host, account_locked'):
            name = args[0]
            self.rows = (('localhost', 'Y' if name in self.db.roles else 'N'),) if name in self.db.roles | self.db.users else ()
        elif sql.startswith('SHOW GRANTS FOR'):
            name = args[0]
            self.rows = (("GRANT USAGE ON *.* TO '" + name + "'@'localhost'",),)
            if name in self.db.bindings:
                self.rows += (("GRANT '" + self.db.bindings[name] + "'@'localhost' TO '" + name + "'@'localhost'",),)
        elif sql.startswith('SELECT FROM_USER, FROM_HOST, TO_USER, TO_HOST'):
            name = args[0]
            self.rows = tuple((r, 'localhost', u, 'localhost') for u, r in self.db.bindings.items() if name in (u, r))
        elif sql.startswith('SELECT DEFAULT_ROLE_USER') or sql.startswith('SELECT FROM_USER, FROM_HOST FROM'):
            self.rows = ((self.db.bindings[args[0]], 'localhost'),) if args[0] in self.db.bindings else ()
        elif sql.startswith('SELECT schema_name FROM'):
            self.rows = tuple((n,) for n in ('rc_demo_biz', 'rc_demo_report', 'rc_demo_audit')) if self.db.populated else ()
        elif sql.startswith('SELECT user, host, account_locked'):
            self.rows = tuple((u, 'localhost', 'N') for u in self.db.users) + tuple((r, 'localhost', 'Y') for r in self.db.roles)
        elif sql.startswith('SELECT u.User, u.Host'):
            self.rows = tuple((u, 'localhost', 'N', 'caching_sha2_password', self.db.bindings.get(u),
                               'localhost' if u in self.db.bindings else None) for u in sorted(self.db.users))
        elif sql.startswith('CREATE ROLE'): self.db.roles.update(r for u, r in PAIRS)
        elif sql.startswith('CREATE DATABASE'): self.db.populated = True
        elif sql.startswith('CREATE USER'): self.db.users.add(args[0])
        elif sql.startswith('GRANT '): self.db.bindings[args[1]] = args[0]


def is_write(sql):
    return sql.startswith(('CREATE ', 'GRANT ', 'SET DEFAULT', 'ALTER ', 'DROP ', 'INSERT ', 'UPDATE ', 'DELETE '))
