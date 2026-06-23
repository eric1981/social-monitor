-- 001: Initial schema — accounts, videos, snapshots, keywords, comments
-- Merged from migrate_db() logic + schema.sql

CREATE TABLE IF NOT EXISTS accounts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    platform          TEXT NOT NULL,
    account_name      TEXT NOT NULL,
    nickname          TEXT,
    sec_uid           TEXT,
    is_active         INTEGER DEFAULT 1,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    follower_count         INTEGER DEFAULT 0,
    total_digg_count       INTEGER DEFAULT 0,
    total_play_count       INTEGER DEFAULT 0,
    total_following_count  INTEGER DEFAULT 0,
    profile_bio            TEXT DEFAULT '',
    profile_douyin_id      TEXT DEFAULT '',
    profile_avatar_url     TEXT DEFAULT '',
    profile_like_count     INTEGER DEFAULT 0,
    account_stats_updated  DATETIME,
    cookie_status          TEXT DEFAULT 'unknown',
    consecutive_failures   INTEGER DEFAULT 0,
    group_id               INTEGER,
    UNIQUE(platform, account_name)
);

CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    platform     TEXT NOT NULL,
    account_name TEXT NOT NULL,
    aweme_id     TEXT NOT NULL,
    title        TEXT,
    duration     INTEGER,
    url          TEXT,
    cover_url    TEXT DEFAULT '',
    first_seen   DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted   INTEGER DEFAULT 0,
    UNIQUE(platform, aweme_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      INTEGER NOT NULL REFERENCES videos(id),
    collected_at  DATETIME NOT NULL,
    play_count    INTEGER DEFAULT 0,
    digg_count    INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    share_count   INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    UNIQUE(video_id, collected_at)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_video_time ON snapshots(video_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_videos_account ON videos(account_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_collected ON snapshots(collected_at);

CREATE TABLE IF NOT EXISTS keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT NOT NULL,
    platform    TEXT,
    account_id  INTEGER,
    color       TEXT DEFAULT 'blue',
    is_active   INTEGER DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id     INTEGER NOT NULL REFERENCES videos(id),
    platform     TEXT NOT NULL,
    comment_id   TEXT NOT NULL,
    author_name  TEXT,
    content      TEXT NOT NULL,
    digg_count   INTEGER DEFAULT 0,
    create_time  DATETIME,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    matched_kw   TEXT DEFAULT '',
    UNIQUE(platform, comment_id)
);

CREATE INDEX IF NOT EXISTS idx_comments_matched ON comments(matched_kw);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
