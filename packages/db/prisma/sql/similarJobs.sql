-- similarJobs.sql — nearest job embeddings by cosine distance.
-- TypedSQL: $queryRawTyped(similarJobs(queryEmbedding, limit))
-- queryEmbedding: '[0.1,0.2,...]'::vector literal string (3072-d).

SELECT o.url_hash, o.url, o.title, c.normalized_company AS company,
       e.embedding <=> $1::vector AS distance
FROM obs_embeddings e
JOIN job_observations o ON o.url_hash = e.url_hash
LEFT JOIN radar_candidates c ON c.canonical_id = e.url_hash
ORDER BY e.embedding <=> $1::vector
LIMIT $2;
