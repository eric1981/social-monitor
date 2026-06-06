-- social-monitor 数据库 schema
-- 平台: douyin, kuaishou, xiaohongshu, shipinhao

CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    platform     TEXT NOT NULL,         -- 'douyin' | 'kuaishou' | 'xiaohongshu' | 'shipinhao'
    account_name TEXT NOT NULL,         -- 自定义标识: 'benxian1', 'benxian-app', 等
    nickname     TEXT,                  -- 平台显示名称
    sec_uid      TEXT,                  -- 平台用户标识（用于API查询）
    is_active    INTEGER DEFAULT 1,     -- 是否在监控中
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    follower_count      INTEGER DEFAULT 0,   -- 粉丝数
    total_digg_count    INTEGER DEFAULT 0,   -- 总获赞数
    total_play_count    INTEGER DEFAULT 0,   -- 总播放数
    total_following_count INTEGER DEFAULT 0, -- 关注数
    profile_bio         TEXT DEFAULT '',      -- 个人简介
    profile_douyin_id   TEXT DEFAULT '',      -- 抖音号
    profile_avatar_url  TEXT DEFAULT '',      -- 头像URL
    profile_like_count  INTEGER DEFAULT 0,   -- 主页获赞数
    account_stats_updated DATETIME,           -- 账号统计信息上次更新时间
    UNIQUE(platform, account_name)
);

CREATE TABLE IF NOT EXISTS videos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    platform     TEXT NOT NULL,
    account_name TEXT NOT NULL,
    aweme_id     TEXT NOT NULL,         -- 平台视频唯一ID
    title        TEXT,                  -- 标题
    duration     INTEGER,              -- 时长（秒）
    url          TEXT,                  -- 播放地址
    first_seen   DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted   INTEGER DEFAULT 0,
    UNIQUE(platform, aweme_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id       INTEGER NOT NULL REFERENCES videos(id),
    collected_at   DATETIME NOT NULL,    -- 采集时间
    play_count     INTEGER DEFAULT 0,
    digg_count     INTEGER DEFAULT 0,
    comment_count  INTEGER DEFAULT 0,
    share_count    INTEGER DEFAULT 0,
    collect_count  INTEGER DEFAULT 0,
    UNIQUE(video_id, collected_at)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_video_time
    ON snapshots(video_id, collected_at);

CREATE INDEX IF NOT EXISTS idx_videos_account
    ON videos(account_id);

CREATE INDEX IF NOT EXISTS idx_snapshots_collected
    ON snapshots(collected_at);
