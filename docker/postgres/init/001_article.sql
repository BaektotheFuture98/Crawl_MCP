-- Local Compose bootstrap only. Production ARTICLE is owned by the existing database schema.
CREATE TABLE IF NOT EXISTS article (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    ar_title TEXT,
    ar_content TEXT,
    reporter VARCHAR(100),
    publisher VARCHAR(100),
    url TEXT,
    published_at TIMESTAMP
);
