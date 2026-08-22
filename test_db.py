import sqlite3, os
db = os.path.expanduser('~/.publikclip/db.sqlite3')
conn = sqlite3.connect(db)
c = conn.cursor()
c.execute("SELECT status, error FROM jobs WHERE id='20260820-172550-6ff85a'")
print(c.fetchone())
