import sqlite3
import json

DB = r"D:\QQBot\AstrBot\data\data_v4.db"
con = sqlite3.connect(DB)
cur = con.cursor()
tables = [r[0] for r in cur.execute("select name from sqlite_master where type='table'")]
print("TABLES:", tables)
for t in tables:
    if "persona" in t.lower():
        print("\n==", t)
        cols = [c[1] for c in cur.execute(f"pragma table_info({t})")]
        print("COLS:", cols)
        for row in cur.execute(f"select * from {t}"):
            print(dict(zip(cols, row)))
