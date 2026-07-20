import { useState, useEffect } from "react";
import { useAuth } from "../contexts/auth_context";
import { supabase } from "../lib/supabase_client";
import { CommunicationStyleType } from "../constants/quiz_constants";
import { CommunicationStyleQuiz } from "../components/communication_style_quiz";

const SESSION_STORAGE_KEY = "copefy_session_id";

const COMMUNICATION_STYLES: {
  value: CommunicationStyleType;
  label: string;
  description: string;
  icon: string;
}[] = [
  {
    value: "Gentle & Supportive",
    label: "Gentle & Supportive",
    description: "Soft, empathetic, and encouraging feedback.",
    icon: "🌱",
  },
  {
    value: "Motivational & Encouraging",
    label: "Motivational & Encouraging",
    description: "High-energy, positive reinforcement and drive.",
    icon: "🔥",
  },
  {
    value: "Direct & Action-Oriented",
    label: "Direct & Action-Oriented",
    description: "Straightforward, practical next steps and solutions.",
    icon: "🎯",
  },
  {
    value: "Calm & Reflective",
    label: "Calm & Reflective",
    description: "Thoughtful, listening-focused, peaceful presence.",
    icon: "🌊",
  },
];

// Helper to parse the raw wellness_goal column into primary goal & optional context
function parse_wellness_goal(raw: string | null): {
  primary_goal: string;
  additional_context: string;
} {
  if (!raw) return { primary_goal: "", additional_context: "" };
  const delimiter = "\n\nAdditional Context:\n";
  const index = raw.indexOf(delimiter);
  if (index !== -1) {
    return {
      primary_goal: raw.substring(0, index).trim(),
      additional_context: raw.substring(index + delimiter.length).trim(),
    };
  }
  return { primary_goal: raw.trim(), additional_context: "" };
}

function SettingsPage() {
  const { profile, updateProfile } = useAuth();

  // Preferred Name state
  const [preferred_name, set_preferred_name] = useState("");
  const [saving_name, set_saving_name] = useState(false);
  const [name_error, set_name_error] = useState<string | null>(null);
  const [name_success, set_name_success] = useState<string | null>(null);

  // Communication Style state
  const [communication_style, set_communication_style] = useState<string | null>(null);
  const [custom_style, set_custom_style] = useState("");
  const [saving_style, set_saving_style] = useState(false);
  const [style_error, set_style_error] = useState<string | null>(null);
  const [style_success, set_style_success] = useState<string | null>(null);
  const [quiz_active, set_quiz_active] = useState(false);
  const [recommendation_message, set_recommendation_message] = useState<string | null>(null);

  // Wellness Goal state
  const [primary_goal, set_primary_goal] = useState("");
  const [additional_context, set_additional_context] = useState("");
  const [saving_goal, set_saving_goal] = useState(false);
  const [goal_error, set_goal_error] = useState<string | null>(null);
  const [goal_success, set_goal_success] = useState<string | null>(null);

  // Account state
  const [logout_loading, set_logout_loading] = useState(false);

  // Sync state when profile loads/updates
  useEffect(() => {
    if (profile) {
      set_preferred_name(profile.preferred_name || "");

      // Check if communication_style matches one of the presets
      const matched_preset = COMMUNICATION_STYLES.find(
        (s) => s.value === profile.communication_style
      );
      if (matched_preset) {
        set_communication_style(matched_preset.value);
        set_custom_style("");
      } else {
        set_communication_style(null);
        set_custom_style(profile.communication_style || "");
      }

      // Parse wellness goal and context
      const parsed = parse_wellness_goal(profile.wellness_goal);
      set_primary_goal(parsed.primary_goal);
      set_additional_context(parsed.additional_context);
    }
  }, [profile]);

  // Handlers for Preferred Name
  const handle_save_name = async (e: React.FormEvent) => {
    e.preventDefault();
    set_name_error(null);
    set_name_success(null);

    const trimmed = preferred_name.trim();
    if (!trimmed) {
      set_name_error("Preferred name cannot be empty.");
      return;
    }

    set_saving_name(true);
    try {
      await updateProfile({ preferred_name: trimmed });
      set_name_success("Preferred name saved successfully!");
      setTimeout(() => set_name_success(null), 3000);
    } catch (err) {
      console.error("Failed to update name:", err);
      set_name_error("Failed to save preferred name. Please try again.");
    } finally {
      set_saving_name(false);
    }
  };

  // Handlers for Communication Style
  const handle_preset_select = (val: string) => {
    set_communication_style(val);
    set_custom_style("");
    set_recommendation_message(null);
    set_style_error(null);
  };

  const handle_custom_style_change = (val: string) => {
    set_custom_style(val);
    if (val.trim()) {
      set_communication_style(null);
    }
    set_recommendation_message(null);
    set_style_error(null);
  };

  const handle_quiz_complete = (recommended: CommunicationStyleType) => {
    set_communication_style(recommended);
    set_custom_style("");
    set_recommendation_message(`We recommend ${recommended} based on your preferences.`);
    set_quiz_active(false);
  };

  const handle_save_style = async (e: React.FormEvent) => {
    e.preventDefault();
    set_style_error(null);
    set_style_success(null);

    const style_to_save = communication_style || custom_style.trim();
    if (!style_to_save) {
      set_style_error("Please select a communication style preset or enter your own.");
      return;
    }

    set_saving_style(true);
    try {
      await updateProfile({ communication_style: style_to_save });
      set_style_success("Communication style saved successfully!");
      setTimeout(() => set_style_success(null), 3000);
    } catch (err) {
      console.error("Failed to update style:", err);
      set_style_error("Failed to save communication style. Please try again.");
    } finally {
      set_saving_style(false);
    }
  };

  // Handlers for Wellness Goal
  const handle_save_goal = async (e: React.FormEvent) => {
    e.preventDefault();
    set_goal_error(null);
    set_goal_success(null);

    const trimmed_primary = primary_goal.trim();
    if (!trimmed_primary) {
      set_goal_error("Wellness goal cannot be empty.");
      return;
    }

    const goal_to_save = additional_context.trim()
      ? `${trimmed_primary}\n\nAdditional Context:\n${additional_context.trim()}`
      : trimmed_primary;

    set_saving_goal(true);
    try {
      await updateProfile({ wellness_goal: goal_to_save });
      set_goal_success("Wellness goal saved successfully!");
      setTimeout(() => set_goal_success(null), 3000);
    } catch (err) {
      console.error("Failed to update wellness goal:", err);
      set_goal_error("Failed to save wellness goal. Please try again.");
    } finally {
      set_saving_goal(false);
    }
  };

  // Handler for Log Out
  const handle_logout = async () => {
    set_logout_loading(true);
    try {
      await supabase.auth.signOut();
      localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch (error) {
      console.error("Failed to sign out:", error);
      set_logout_loading(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      <header className="flex shrink-0 items-center border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-base font-bold text-slate-800">Settings</h1>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-2xl flex flex-col gap-6">
          
          {/* SECTION 1: PREFERRED NAME */}
          <section className="rounded-2xl bg-white p-6 shadow-xs ring-1 ring-slate-200">
            <h2 className="text-base font-bold text-slate-900">Preferred Name</h2>
            <p className="mt-1 text-xs text-slate-500">
              Update how Copefy addresses you during coaching conversations.
            </p>

            {name_error && (
              <div className="mt-4 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-600">
                {name_error}
              </div>
            )}
            {name_success && (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 font-medium">
                {name_success}
              </div>
            )}

            <form onSubmit={handle_save_name} className="mt-4 flex flex-col gap-4">
              <div>
                <label
                  htmlFor="settings_preferred_name"
                  className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1"
                >
                  Preferred Name
                </label>
                <input
                  id="settings_preferred_name"
                  type="text"
                  value={preferred_name}
                  onChange={(e) => set_preferred_name(e.target.value)}
                  maxLength={50}
                  placeholder="What should we call you?"
                  className="w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={saving_name}
                  className="rounded-full bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white transition-all hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving_name ? "Saving Name..." : "Save Name"}
                </button>
              </div>
            </form>
          </section>

          {/* SECTION 2: COMMUNICATION STYLE */}
          <section className="rounded-2xl bg-white p-6 shadow-xs ring-1 ring-slate-200">
            <h2 className="text-base font-bold text-slate-900">Communication Style</h2>
            <p className="mt-1 text-xs text-slate-500">
              Customize how Copefy phrases feedback, guidance, and encouragement.
            </p>

            {style_error && (
              <div className="mt-4 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-600">
                {style_error}
              </div>
            )}
            {style_success && (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 font-medium">
                {style_success}
              </div>
            )}

            {!quiz_active ? (
              <form onSubmit={handle_save_style} className="mt-5 flex flex-col gap-5">
                
                {/* Recommendation Banner */}
                {recommendation_message && (
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 p-3.5 text-xs font-medium text-emerald-900 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-base">✨</span>
                      <span>{recommendation_message}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => set_recommendation_message(null)}
                      className="text-emerald-700 hover:text-emerald-950 font-bold ml-2 px-1"
                    >
                      ✕
                    </button>
                  </div>
                )}

                {/* Presets Grid */}
                <div>
                  <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2.5 px-1">
                    Select a Style Preset
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {COMMUNICATION_STYLES.map((style) => {
                      const is_selected = communication_style === style.value;
                      return (
                        <button
                          key={style.value}
                          type="button"
                          onClick={() => handle_preset_select(style.value)}
                          className={`flex flex-col items-start text-left p-4 rounded-xl border transition-all relative outline-none ${
                            is_selected
                              ? "border-indigo-600 bg-indigo-50/30 ring-2 ring-indigo-100"
                              : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/50"
                          }`}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xl">{style.icon}</span>
                            <span className={`text-sm font-semibold ${is_selected ? "text-indigo-900" : "text-slate-800"}`}>
                              {style.label}
                            </span>
                          </div>
                          <p className="text-xs text-slate-500 leading-relaxed">
                            {style.description}
                          </p>
                          {is_selected && (
                            <span className="absolute bottom-3 right-3 flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white">
                              <svg
                                className="h-3 w-3"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth="2.5"
                                  d="M5 13l4 4L19 7"
                                />
                              </svg>
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Custom Style Input */}
                <div>
                  <label
                    htmlFor="settings_custom_style"
                    className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1"
                  >
                    Or Describe Your Own Style
                  </label>
                  <input
                    id="settings_custom_style"
                    type="text"
                    value={custom_style}
                    onChange={(e) => handle_custom_style_change(e.target.value)}
                    placeholder="e.g., direct but compassionate, or using structured and analytical language..."
                    className="w-full rounded-xl border border-slate-300 px-4 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                  />
                </div>

                {/* Quiz Promo Card */}
                <div className="rounded-2xl border border-indigo-100 bg-indigo-50/50 p-4 text-center">
                  <h3 className="text-sm font-bold text-indigo-900">
                    Not sure which style fits you best?
                  </h3>
                  <p className="mt-1 text-xs text-indigo-700/80 max-w-md mx-auto leading-relaxed">
                    Retake our quick 1-minute preference quiz anytime to find your ideal coaching style.
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      set_quiz_active(true);
                      set_style_error(null);
                    }}
                    className="mt-3 rounded-full bg-indigo-600 px-5 py-2 text-xs font-semibold text-white transition-all hover:bg-indigo-700 shadow-xs"
                  >
                    Take the Quiz
                  </button>
                </div>

                <div className="flex justify-end">
                  <button
                    type="submit"
                    disabled={saving_style}
                    className="rounded-full bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white transition-all hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {saving_style ? "Saving Style..." : "Save Communication Style"}
                  </button>
                </div>
              </form>
            ) : (
              <div className="mt-4">
                <CommunicationStyleQuiz
                  onComplete={handle_quiz_complete}
                  onCancel={() => set_quiz_active(false)}
                />
              </div>
            )}
          </section>

          {/* SECTION 3: WELLNESS GOALS & CONTEXT */}
          <section className="rounded-2xl bg-white p-6 shadow-xs ring-1 ring-slate-200">
            <h2 className="text-base font-bold text-slate-900">Wellness Goals & Personalization</h2>
            <p className="mt-1 text-xs text-slate-500">
              Manage what you'd like to work on and specific preferences for AI coaching.
            </p>

            {goal_error && (
              <div className="mt-4 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-600">
                {goal_error}
              </div>
            )}
            {goal_success && (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800 font-medium">
                {goal_success}
              </div>
            )}

            <form onSubmit={handle_save_goal} className="mt-5 flex flex-col gap-5">
              {/* Primary Goal */}
              <div>
                <label
                  htmlFor="settings_primary_goal"
                  className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1"
                >
                  Wellness Goal
                </label>
                <textarea
                  id="settings_primary_goal"
                  rows={4}
                  value={primary_goal}
                  onChange={(e) => set_primary_goal(e.target.value)}
                  placeholder="e.g., I want to build a daily mindfulness habit, reduce stress before exams, and find healthier ways to manage anxiety..."
                  className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 resize-none leading-relaxed"
                />
              </div>

              {/* Personalization Context */}
              <div>
                <label
                  htmlFor="settings_additional_context"
                  className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-1"
                >
                  Anything you'd like the AI to keep in mind during conversations? (Optional)
                </label>
                <textarea
                  id="settings_additional_context"
                  rows={3}
                  value={additional_context}
                  onChange={(e) => set_additional_context(e.target.value)}
                  placeholder="e.g., I prefer practical exercises over open-ended journaling, or I have a busy schedule and prefer quick tips."
                  className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 resize-none leading-relaxed"
                />
              </div>

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={saving_goal}
                  className="rounded-full bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white transition-all hover:bg-indigo-700 disabled:opacity-50"
                >
                  {saving_goal ? "Saving Goals..." : "Save Wellness Goals"}
                </button>
              </div>
            </form>
          </section>

          {/* SECTION 4: ACCOUNT */}
          <section className="rounded-2xl bg-white p-6 shadow-xs ring-1 ring-slate-200">
            <h2 className="text-base font-bold text-slate-900">Account</h2>
            <p className="mt-1 text-xs text-slate-500">
              Sign out of your Copefy account on this device.
            </p>
            <button
              type="button"
              onClick={handle_logout}
              disabled={logout_loading}
              className="mt-4 rounded-full bg-red-600 px-5 py-2 text-xs font-semibold text-white transition-colors hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {logout_loading ? "Signing out..." : "Log Out"}
            </button>
          </section>

        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
