-- Run in Supabase SQL editor if your profiles table predates this column.
ALTER TABLE profiles
ADD COLUMN IF NOT EXISTS coaching_preferences TEXT;
