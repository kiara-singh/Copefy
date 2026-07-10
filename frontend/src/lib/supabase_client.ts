import { createClient } from "@supabase/supabase-js";

const supabase_url = import.meta.env.VITE_SUPABASE_URL;
const supabase_anon_key = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabase_url || !supabase_anon_key) {
  // Surfaced early so a missing .env is obvious during development.
  console.warn(
    "Supabase env vars are missing. Copy .env.example to .env and fill in VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY."
  );
}

export const supabase = createClient(supabase_url ?? "", supabase_anon_key ?? "");
