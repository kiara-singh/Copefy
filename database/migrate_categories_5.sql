-- Collapse gad/panic_disorder/phobias/social_anxiety into top-level anxiety.
-- Run once via: python -m rag.migrate_categories (from backend/, venv active)
-- Or paste into the Supabase SQL editor.

BEGIN;

ALTER TABLE kb_documents
    ADD COLUMN IF NOT EXISTS anxiety_subtype TEXT;

-- Backfill subtype from former primary before rewriting category.
UPDATE kb_documents
SET anxiety_subtype = category
WHERE category IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety')
  AND anxiety_subtype IS NULL;

-- Subtype from junction primary when document primary is not anxiety yet.
UPDATE kb_documents d
SET anxiety_subtype = sub.cat
FROM (
    SELECT dc.document_id, dc.category AS cat
    FROM kb_document_categories dc
    WHERE dc.is_primary = TRUE
      AND dc.category IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety')
) sub
WHERE d.id = sub.document_id
  AND d.anxiety_subtype IS NULL;

-- Default remaining anxiety primaries without subtype to gad (general anxiety pages).
UPDATE kb_documents
SET anxiety_subtype = 'gad'
WHERE category IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety', 'anxiety')
  AND anxiety_subtype IS NULL;

-- Drop old CHECK constraints before rewriting category values.
ALTER TABLE kb_documents DROP CONSTRAINT IF EXISTS kb_documents_category_check;
ALTER TABLE kb_document_categories DROP CONSTRAINT IF EXISTS kb_document_categories_category_check;

UPDATE kb_documents
SET category = 'anxiety'
WHERE category IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety');

-- Ensure one anxiety label per doc that is anxiety-primary or had an anxiety label.
INSERT INTO kb_document_categories (document_id, category, confidence, is_primary)
SELECT DISTINCT d.id, 'anxiety', 1.0, (d.category = 'anxiety')
FROM kb_documents d
WHERE d.status = 'active'
  AND (
      d.category = 'anxiety'
      OR EXISTS (
          SELECT 1 FROM kb_document_categories dc
          WHERE dc.document_id = d.id
            AND dc.category IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety')
      )
  )
ON CONFLICT (document_id, category) DO UPDATE
SET is_primary = EXCLUDED.is_primary;

DELETE FROM kb_document_categories
WHERE category IN ('gad', 'panic_disorder', 'phobias', 'social_anxiety');

ALTER TABLE kb_documents
    ADD CONSTRAINT kb_documents_category_check CHECK (
        category IN ('adhd', 'depression', 'anxiety', 'ocd', 'ptsd')
    );

ALTER TABLE kb_documents DROP CONSTRAINT IF EXISTS kb_documents_anxiety_subtype_check;
ALTER TABLE kb_documents
    ADD CONSTRAINT kb_documents_anxiety_subtype_check CHECK (
        anxiety_subtype IS NULL
        OR (
            category = 'anxiety'
            AND anxiety_subtype IN (
                'gad', 'panic_disorder', 'phobias', 'social_anxiety'
            )
        )
    );

ALTER TABLE kb_document_categories
    ADD CONSTRAINT kb_document_categories_category_check CHECK (
        category IN ('adhd', 'depression', 'anxiety', 'ocd', 'ptsd')
    );

CREATE INDEX IF NOT EXISTS kb_documents_anxiety_subtype_idx
    ON kb_documents (anxiety_subtype)
    WHERE anxiety_subtype IS NOT NULL;

COMMIT;
