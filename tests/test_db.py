import sqlite3
import os

db_path = "../database/kiosk_music.db"
print(f"Database exists: {os.path.exists(db_path)}")
print(f"Database location: {os.path.abspath(db_path)}")

if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"\nTables in database: {[t[0] for t in tables]}")

    # Check if we have the right tables
    expected_tables = ['songs', 'fingerprints', 'track_metadata']
    for table in expected_tables:
        if table in [t[0] for t in tables]:
            print(f"{table} table exists")
        else:
            print(f"{table} table MISSING")

    # Check track_metadata contents
    try:
        cursor.execute("SELECT COUNT(*) FROM track_metadata")
        count = cursor.fetchone()[0]
        print(f"\nTracks in metadata: {count}")

        if count > 0:
            cursor.execute("SELECT * FROM track_metadata LIMIT 5")
            print("\nSample tracks:")
            for row in cursor.fetchall():
                print(f"  ID: {row[0]}, Title: {row[1]}, Artist: {row[2]}")
    except sqlite3.OperationalError as e:
        print(f"Error reading track_metadata: {e}")

    conn.close()
else:
    print("Database file not found!")