CREATE TABLE IF NOT EXISTS tracks (
    track_id      BIGINT PRIMARY KEY,      
    title         TEXT NOT NULL,
    genre         TEXT,                    
    created_at    TIMESTAMPTZ,             
    first_seen_at TIMESTAMPTZ DEFAULT now() 
);

CREATE TABLE IF NOT EXISTS track_snapshots (
    track_id          BIGINT NOT NULL REFERENCES tracks(track_id),
    snapshot_date     DATE NOT NULL,
    playback_count    INT,
    favoritings_count INT,   -- likes on the track (NOT the same as user.likes_count)
    reposts_count     INT,
    comment_count     INT,
    download_count    INT,
    PRIMARY KEY (track_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS account_snapshots (
    snapshot_date           DATE PRIMARY KEY,
    followers_count         INT,
    followings_count        INT,
    public_favorites_count  INT,  
    reposts_count           INT   
);