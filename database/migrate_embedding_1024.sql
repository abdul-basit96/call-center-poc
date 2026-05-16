-- Run once if doctors.embedding was created as vector(384) (old MiniLM).
-- Then: FORCE_EMBED_DOCTORS=true uv run python -m scripts.seed_db

ALTER TABLE doctors DROP COLUMN IF EXISTS embedding;
ALTER TABLE doctors ADD COLUMN embedding vector(1024);
