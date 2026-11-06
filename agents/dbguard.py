"""Refuse to reuse a sqlite database built for another deployment or an older schema.

A redeploy restarts subIds and nodeIds at 1, so rows indexed from the old contracts would silently shadow
the new ones (INSERT OR IGNORE). An older schema lacks columns the code now writes. Either way the only
safe move is a fresh database, so we stop and say so.
"""


class WrongDatabase(Exception):
    pass


def bind(db, deployment: str, schema: int, has_data_sql: str) -> None:
    """Record (deployment, schema) on first use; afterwards require they match.

    has_data_sql: a query returning a row if the database already holds data (so an unlabeled, used
    database from an older version is rejected instead of being adopted).
    """
    db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    meta = dict(db.execute("SELECT k, v FROM meta").fetchall())
    want = {"deployment": deployment, "schema": str(schema)}
    if not meta:
        if db.execute(has_data_sql).fetchone():
            raise WrongDatabase("this database was built by an older version; delete it and restart")
        with db:
            db.executemany("INSERT INTO meta VALUES (?, ?)", want.items())
        return
    if meta != want:
        raise WrongDatabase(f"this database belongs to {meta}, not {want}; delete it and restart")
