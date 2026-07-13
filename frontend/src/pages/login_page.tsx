import { useState } from "react";
import { supabase } from "../lib/supabase_client";

function LoginPage() {
  const [is_sign_up, set_is_sign_up] = useState(false);
  const [email, set_email] = useState("");
  const [password, set_password] = useState("");
  const [confirm_password, set_confirm_password] = useState("");

  const [show_password, set_show_password] = useState(false);
  const [show_confirm_password, set_show_confirm_password] = useState(false);

  const [loading, set_loading] = useState(false);
  const [error, set_error] = useState<string | null>(null);
  const [success, set_success] = useState<string | null>(null);

  const validate_email = (value: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  };

  const get_friendly_error_message = (msg: string): string => {
    const lower = msg.toLowerCase();
    if (lower.includes("invalid login credentials")) {
      return "Invalid email or password.";
    }
    if (lower.includes("user already registered")) {
      return "An account with this email already exists.";
    }
    if (lower.includes("password should be at least 6 characters")) {
      return "Password must be at least 6 characters long.";
    }
    return msg;
  };

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    set_error(null);
    set_success(null);

    const email_trimmed = email.trim();
    if (!email_trimmed || !password) {
      set_error("Please fill in all required fields.");
      return;
    }

    if (!validate_email(email_trimmed)) {
      set_error("Please enter a valid email address.");
      return;
    }

    if (is_sign_up && password.length < 6) {
      set_error("Password must be at least 6 characters long.");
      return;
    }

    if (is_sign_up && password !== confirm_password) {
      set_error("Passwords do not match.");
      return;
    }

    set_loading(true);

    try {
      if (is_sign_up) {
        const { data, error: sign_up_error } = await supabase.auth.signUp({
          email: email_trimmed,
          password: password,
        });

        if (sign_up_error) {
          set_error(get_friendly_error_message(sign_up_error.message));
        } else if (data?.user && !data.session) {
          // User signed up, but email confirmation is active
          set_success(
            "Account registration successful! Please check your email inbox to verify your account."
          );
          set_email("");
          set_password("");
          set_confirm_password("");
        }
      } else {
        const { error: sign_in_error } =
          await supabase.auth.signInWithPassword({
            email: email_trimmed,
            password: password,
          });

        if (sign_in_error) {
          set_error(get_friendly_error_message(sign_in_error.message));
        }
      }
    } catch (err: unknown) {
      console.error("Auth operation failed:", err);
      set_error("An unexpected error occurred. Please try again.");
    } finally {
      set_loading(false);
    }
  };

  const toggle_mode = () => {
    set_is_sign_up(!is_sign_up);
    set_error(null);
    set_success(null);
    set_password("");
    set_confirm_password("");
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-md bg-white rounded-2xl p-8 shadow-sm ring-1 ring-slate-200">
        <div className="text-center mb-6">
          <span className="text-3xl font-extrabold tracking-tight text-indigo-600">
            Copefy
          </span>
          <h2 className="mt-3 text-xl font-semibold text-slate-900">
            {is_sign_up ? "Create your account" : "Welcome back"}
          </h2>
          <p className="mt-1.5 text-xs text-slate-500">
            {is_sign_up
              ? "Start your path to mindfulness and emotional support"
              : "Sign in to continue your mindfulness journey"}
          </p>
        </div>

        {/* Tab Selector */}
        <div className="flex bg-slate-100 p-1 rounded-full mb-6">
          <button
            type="button"
            onClick={() => is_sign_up && toggle_mode()}
            className={`flex-1 py-1.5 text-center text-xs font-semibold rounded-full transition-all ${
              !is_sign_up
                ? "bg-white text-indigo-600 shadow-sm"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => !is_sign_up && toggle_mode()}
            className={`flex-1 py-1.5 text-center text-xs font-semibold rounded-full transition-all ${
              is_sign_up
                ? "bg-white text-indigo-600 shadow-sm"
                : "text-slate-500 hover:text-slate-800"
            }`}
          >
            Register
          </button>
        </div>

        {/* Alert banners */}
        {error && (
          <div className="mb-4 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-600 flex items-start gap-2">
            <svg
              className="h-4 w-4 shrink-0 text-red-500 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
            <span>{error}</span>
          </div>
        )}

        {success && (
          <div className="mb-4 rounded-xl border border-green-100 bg-green-50 p-3 text-xs text-green-700 flex items-start gap-2">
            <svg
              className="h-4 w-4 shrink-0 text-green-600 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span>{success}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handle_submit} className="flex flex-col gap-4">
          <div>
            <label
              htmlFor="email"
              className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 px-2"
            >
              Email Address
            </label>
            <input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => set_email(e.target.value)}
              placeholder="name@example.com"
              className="w-full rounded-full border border-slate-300 px-4 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </div>

          <div>
            <label
              htmlFor="password"
              className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 px-2"
            >
              Password
            </label>
            <div className="relative">
              <input
                id="password"
                type={show_password ? "text" : "password"}
                required
                value={password}
                onChange={(e) => set_password(e.target.value)}
                placeholder="••••••••"
                className="w-full rounded-full border border-slate-300 pl-4 pr-11 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              />
              <button
                type="button"
                onClick={() => set_show_password(!show_password)}
                className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                title={show_password ? "Hide password" : "Show password"}
              >
                {show_password ? (
                  <svg
                    className="h-5 w-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.75"
                      d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                    />
                  </svg>
                ) : (
                  <svg
                    className="h-5 w-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.75"
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                    />
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="1.75"
                      d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {is_sign_up && (
            <div>
              <label
                htmlFor="confirm_password"
                className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 px-2"
              >
                Confirm Password
              </label>
              <div className="relative">
                <input
                  id="confirm_password"
                  type={show_confirm_password ? "text" : "password"}
                  required
                  value={confirm_password}
                  onChange={(e) => set_confirm_password(e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-full border border-slate-300 pl-4 pr-11 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
                <button
                  type="button"
                  onClick={() =>
                    set_show_confirm_password(!show_confirm_password)
                  }
                  className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                  title={
                    show_confirm_password ? "Hide password" : "Show password"
                  }
                >
                  {show_confirm_password ? (
                    <svg
                      className="h-5 w-5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.75"
                        d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                      />
                    </svg>
                  ) : (
                    <svg
                      className="h-5 w-5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.75"
                        d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                      />
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="1.75"
                        d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                      />
                    </svg>
                  )}
                </button>
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full shrink-0 rounded-full bg-indigo-600 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 flex items-center justify-center gap-2 mt-2"
          >
            {loading ? (
              <>
                <svg
                  className="animate-spin h-4 w-4 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                <span>Processing...</span>
              </>
            ) : is_sign_up ? (
              "Sign Up"
            ) : (
              "Sign In"
            )}
          </button>
        </form>

        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={toggle_mode}
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            {is_sign_up
              ? "Already have an account? Sign In"
              : "Don't have an account? Register"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
