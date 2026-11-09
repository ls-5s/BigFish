import sqlite3

DB = r"D:\QQBot\AstrBot\data\data_v4.db"
con = sqlite3.connect(DB)
cur = con.cursor()
for row in cur.execute("select persona_id, length(system_prompt), updated_at from personas"):
    print(row)
with open(r"D:\QQBot\_debug\persona_dump.txt", "w", encoding="utf-8") as f:
    for pid, sp, upd in cur.execute("select persona_id, system_prompt, updated_at from personas"):
        f.write(f"===== {pid} | {upd} | {len(sp)} chars =====\n{sp}\n\n")
print("dumped")
