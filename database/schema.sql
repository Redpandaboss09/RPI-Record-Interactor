CREATE TABLE IF NOT EXISTS track_metadata (
    dejavu_song_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT,
    album_art_path TEXT,
    lyrics_file TEXT,
    duration REAL,
    date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_track_artist ON track_metadata(artist);
CREATE INDEX IF NOT EXISTS idx_track_album ON track_metadata(album);