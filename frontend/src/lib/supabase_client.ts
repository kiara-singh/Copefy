import { createClient } from "@supabase/supabase-js";

const supabase_url = import.meta.env.VITE_SUPABASE_URL;
const supabase_anon_key = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabase_url || !supabase_anon_key) {
  console.warn(
    "Supabase env vars are missing. Copy frontend/.env.example to .env and set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY (anon public key only)."
  );
}

if (supabase_anon_key?.startsWith("sb_secret_")) {
  console.error(
    "VITE_SUPABASE_ANON_KEY is set to a service-role secret. Use the anon PUBLIC key from Supabase -> Project Settings -> API instead. Profile save will fail until this is fixed."
  );
}

export const supabase = createClient(supabase_url ?? "", supabase_anon_key ?? "");
