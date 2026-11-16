ALTER TABLE items ADD COLUMN progress_percent INTEGER
    CHECK (progress_percent IS NULL OR (typeof(progress_percent) = 'integer' AND progress_percent BETWEEN 0 AND 100));
