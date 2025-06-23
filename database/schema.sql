CREATE DATABASE kiosk_music;

CREATE TABLE track_metadata (
    fingerprint_id INTEGER PRIMARY KEY,
    title VARCHAR(255),
    artist VARCHAR(255),
    album VARCHAR(255),
    album_art_path VARCHAR(500),
    lyrics_file VARCHAR(500),
    duration FLOAT
);