# Sanity check: if this prints my username and the Stockholm
# region, key-pair auth is working and Python can reach Snowflake.

from sf_connect import get_connection

conn = get_connection()
try:
    cur = conn.cursor()
    cur.execute("SELECT CURRENT_USER(), CURRENT_REGION(), CURRENT_ACCOUNT()")
    user, region, account = cur.fetchone()
    print("Connected!")
    print("User   :", user)
    print("Region :", region)
    print("Account:", account)
finally:
    conn.close()