"""Plan forward monthly partitions and data-preserving inverse; NEVER executes DDL."""
import argparse
import datetime
import getpass
from logical_backup import guard


def month(text):
    value = datetime.datetime.strptime(text, '%Y-%m').date()
    if value.strftime('%Y-%m') != text: raise ValueError('Expected YYYY-MM')
    return value


def next_month(value):
    return datetime.date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def plan(existing, through):
    """existing is ordered (name, upper boundary date or MAXVALUE)."""
    if len(existing) < 2 or existing[0][0] != 'p_before' or existing[-1] != ('p_future','MAXVALUE'):
        raise ValueError('Unknown partition layout; manual review required')
    if len({name for name,_ in existing}) != len(existing): raise ValueError('Duplicate partition')
    boundary = existing[0][1]
    if not isinstance(boundary, datetime.date) or boundary.day != 1: raise ValueError('Not a monthly boundary')
    for name, upper in existing[1:-1]:
        if name != 'p'+boundary.strftime('%Y%m') or upper != next_month(boundary):
            raise ValueError('Noncontiguous or renamed monthly partitions')
        boundary = upper
    if through < boundary or through.day != 1: raise ValueError('Target already partitioned or not a month start')
    new = []
    while boundary <= through:
        upper = next_month(boundary)
        new.append(('p'+boundary.strftime('%Y%m'),upper))
        boundary = upper
        if len(new) > 120: raise ValueError('Plan exceeds bounded maintenance window')
    definitions = ["PARTITION `"+name+"` VALUES LESS THAN ('"+upper.isoformat()+"')" for name,upper in new]
    definitions.append('PARTITION `p_future` VALUES LESS THAN (MAXVALUE)')
    forward = 'ALTER TABLE `rc_demo_biz`.`txn` REORGANIZE PARTITION `p_future` INTO (\n  '+',\n  '.join(definitions)+'\n);'
    names = ','.join('`'+name+'`' for name,_ in new)+',`p_future`'
    inverse = 'ALTER TABLE `rc_demo_biz`.`txn` REORGANIZE PARTITION '+names+' INTO (PARTITION `p_future` VALUES LESS THAN (MAXVALUE));'
    return forward,inverse


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--through',required=True,help='Last new month, YYYY-MM')
    parser.add_argument('--live-user',help='Optional: inspect real layout read-only after deployment')
    args=parser.parse_args()
    if args.live_user:
        import pymysql
        with pymysql.connect(host='127.0.0.1',port=3307,user=args.live_user,password=getpass.getpass('Read credential: ')) as conn:
            guard(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT partition_name,partition_description FROM information_schema.partitions WHERE table_schema='rc_demo_biz' AND table_name='txn' ORDER BY partition_ordinal_position")
                existing=[(name,description if description=='MAXVALUE' else datetime.datetime.fromisoformat(description.strip("'")).date()) for name,description in cur.fetchall()]
    else:
        existing=[('p_before',month('2026-10')),('p202610',month('2026-11')),('p202611',month('2026-12')),('p202612',month('2027-01')),('p_future','MAXVALUE')]
    forward,inverse=plan(existing,month(args.through))
    print('-- PLAN ONLY. Repeat live identity/layout verification and approve a maintenance window before DDL.')
    print('-- Forward (no DROP PARTITION):\n'+forward)
    print('-- Inverse (preserves rows, merges layout):\n'+inverse)


if __name__ == '__main__': main()
