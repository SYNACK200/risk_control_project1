"""Real PyMySQL encoding/escaping on synthetic credentials; NEVER opens a socket."""
import pymysql
from pymysql.constants import SERVER_STATUS


def decode_mysql_literal(literal, no_backslash):
    assert literal[0] == literal[-1] == "'"
    s = literal[1:-1]
    if no_backslash:
        return s.replace("''", "'")
    decoded = []
    i = 0
    mapping = {'0': '\0', 'n': '\n', 'r': '\r', 'b': '\b', 't': '\t', 'Z': '\x1a'}
    while i < len(s):
        if s[i] == '\\':
            i += 1
            decoded.append(mapping.get(s[i], s[i]))
        else:
            decoded.append(s[i])
        i += 1
    return ''.join(decoded)


fixtures = ['Synthetic-simple-42!', 'Synthetic-quote-\'-42!', 'Synthetic-double-"-42!',
            'Synthetic-backslash-\\n-42!', 'Synthetic-!$`&%-42!', 'Synthetic-é漢字😀-42!',
            '  Synthetic-spaces-42!  ']
count = 0
for no_backslash in (False, True):
    for synthetic in fixtures:
        conn = pymysql.connect(user='rc_demo_app', host='127.0.0.1', port=3307,
                               charset='utf8mb4', password=synthetic.encode('utf-8'), defer_connect=True)
        conn.server_status = SERVER_STATUS.SERVER_STATUS_NO_BACKSLASH_ESCAPES if no_backslash else 0
        packets = []
        conn._execute_command = lambda command, data: packets.append(data)
        conn._read_query_result = lambda **kwargs: 0
        cur = conn.cursor()
        sql = cur.mogrify("CREATE USER %s@'localhost' IDENTIFIED WITH caching_sha2_password BY %s",
                          ('rc_demo_app', synthetic))
        conn.query(sql)  # _execute_command above is an in-memory sink, not a socket.
        # No SQL or credential is printed, stored in files, or sent to a server.
        literal = packets[0].decode('utf-8').split(' BY ', 1)[1]
        recovered = decode_mysql_literal(literal, no_backslash)
        assert recovered == synthetic
        assert recovered.encode('utf-8') == conn.password
        count += 1
print('Real PyMySQL SQL/password encoding: ' + str(count) + ' PASS; synthetic only; no network')
