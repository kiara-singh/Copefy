import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/auth_context";
import { CommunicationStyleType } from "../constants/quiz_constants";
import { CommunicationStyleQuiz } from "../components/communication_style_quiz";

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

function OnboardingPage() {
  const { updateProfile, user } = useAuth();
  const navigate = useNavigate();

  const [step, set_step] = useState(1);
  const [preferred_name, set_preferred_name] = useState("");
  const [communication_style, set_communication_style] = useState<string | null>(null);
  const [custom_communication_style, set_custom_communication_style] = useState("");
  const [wellness_goal, set_wellness_goal] = useState("");
  const [additional_context, set_additional_context] = useState("");

  const [is_submitting, set_is_submitting] = useState(false);
  const [error, set_error] = useState<string | null>(null);

  // Preference Quiz State
  const [quiz_active, set_quiz_active] = useState(false);
  const [recommendation_message, set_recommendation_message] = useState<string | null>(null);

  useEffect(() => {
    set_error(null);
  }, [step]);

  const get_account_name = (): string => {
    if (user?.user_metadata?.full_name) return user.user_metadata.full_name;
    if (user?.user_metadata?.name) return user.user_metadata.name;
    if (user?.email) return user.email.split("@")[0];
    return "Friend";
  };

  const handle_preset_select = (val: string) => {
    set_communication_style(val);
    set_custom_communication_style("");
    set_recommendation_message(null);
    set_error(null);
  };

  const handle_custom_style_change = (val: string) => {
    set_custom_communication_style(val);
    if (val.trim()) {
      set_communication_style(null);
    }
    set_recommendation_message(null);
    set_error(null);
  };

  const handle_quiz_complete = (recommended: CommunicationStyleType) => {
    set_communication_style(recommended);
    set_custom_communication_style("");
    set_recommendation_message(`We recommend ${recommended} based on your preferences.`);
    set_quiz_active(false);
  };

  const handle_next = () => {
    set_error(null);
    if (step === 1) {
      const name_trimmed = preferred_name.trim();
      if (!name_trimmed) {
        set_error("Please enter a preferred name, or click 'Skip' to use your account name.");
        return;
      }
      set_preferred_name(name_trimmed);
      set_step(2);
    } else if (step === 2) {
      if (!communication_style && !custom_communication_style.trim()) {
        set_error("Please select a communication style preference or describe your own.");
        return;
      }
      set_step(3);
    }
  };

  const handle_back = () => {
    set_error(null);
    if (step > 1) {
      set_step(step - 1);
    }
  };

  const handle_skip = () => {
    set_error(null);
    const fallback_name = get_account_name();
    set_preferred_name(fallback_name);
    set_step(2);
  };

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    set_error(null);

    if (step < 3) {
      handle_next();
      return;
    }

    if (!wellness_goal.trim()) {
      set_error("Please share your wellness goal.");
      return;
    }

    set_is_submitting(true);

    try {
      const style_to_save = communication_style || custom_communication_style.trim();
      await updateProfile({
        preferred_name: preferred_name.trim() || null,
        communication_style: style_to_save,
        wellness_goal: wellness_goal.trim(),
        coaching_preferences: additional_context.trim() || null,
        onboarding_complete: true,
      });
      navigate("/", { replace: true });
    } catch (err: unknown) {
      console.error("Failed to complete onboarding:", err);
      const message =
        err && typeof err === "object" && "message" in err && typeof err.message === "string"
          ? err.message
          : "An unexpected error occurred while saving your preferences. Please try again.";
      if (message.toLowerCase().includes("jwt") || message.toLowerCase().includes("api key")) {
        set_error(
          "Supabase is misconfigured. In frontend/.env use the anon PUBLIC key (not the service secret), then restart npm run dev."
        );
      } else {
        set_error(message);
      }
    } finally {
      set_is_submitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-xl bg-white rounded-2xl p-8 shadow-sm ring-1 ring-slate-200">
        
        {/* Brand Header */}
        <div className="text-center mb-6">
          <span className="text-3xl font-extrabold tracking-tight text-indigo-600">
            Copefy
          </span>
        </div>

        {/* Progress Bar / Step Indicators */}
        <div className="flex items-center justify-between mb-8 px-2 max-w-xs mx-auto">
          {[1, 2, 3].map((s) => (
            <div key={s} className="flex items-center flex-1 last:flex-initial">
              <div
                className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition-all ${
                  step >= s
                    ? "bg-indigo-600 text-white shadow-sm shadow-indigo-100"
                    : "bg-slate-100 text-slate-400"
                }`}
              >
                {s}
              </div>
              {s < 3 && (
                <div
                  className={`h-0.5 flex-1 mx-2 transition-all ${
                    step > s ? "bg-indigo-600" : "bg-slate-200"
                  }`}
                />
              )}
            </div>
          ))}
        </div>

        {/* Form Title & Subtitle based on Step */}
        <div className="text-center mb-8">
          {step === 1 && (
            <>
              <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
                Let's personalize your experience
              </h1>
              <p className="mt-2 text-sm text-slate-500 max-w-md mx-auto">
                First, tell us what we should call you.
              </p>
            </>
          )}
          {step === 2 && !quiz_active && (
            <>
              <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
                Choose your coaching style
              </h1>
              <p className="mt-2 text-sm text-slate-500 max-w-md mx-auto">
                How would you like Copefy to talk to you?
              </p>
            </>
          )}
          {step === 3 && (
            <>
              <h1 className="text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
                What are your goals?
              </h1>
              <p className="mt-2 text-sm text-slate-500 max-w-md mx-auto">
                Let us know what you'd like to work on during your time with Copefy.
              </p>
            </>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="mb-6 rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-600 flex items-start gap-2.5">
            <svg
              className="h-5 w-5 shrink-0 text-red-500 mt-0.5"
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

        {/* Wizard Form */}
        <form onSubmit={handle_submit} className="flex flex-col gap-6">
          
          {/* Step 1: Preferred Name */}
          {step === 1 && (
            <div className="transition-all duration-300 ease-in-out">
              <label
                htmlFor="preferred_name"
                className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-2"
              >
                Preferred Name (Optional)
              </label>
              <input
                id="preferred_name"
                type="text"
                value={preferred_name}
                onChange={(e) => set_preferred_name(e.target.value)}
                maxLength={50}
                placeholder="What should we call you?"
                className="w-full rounded-full border border-slate-300 px-4 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
              />
            </div>
          )}

          {/* Step 2: Communication Style - Main Form */}
          {step === 2 && !quiz_active && (
            <div className="flex flex-col gap-5 transition-all duration-300 ease-in-out">
              
              {/* Recommendation Banner */}
              {recommendation_message && (
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/80 p-3.5 text-xs font-medium text-emerald-900 flex items-center justify-between shadow-xs">
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

              <div>
                <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2.5 px-2">
                  Communication Style Preset <span className="text-red-500">*</span>
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
              <div className="mt-1">
                <label
                  htmlFor="custom_style"
                  className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5 px-2"
                >
                  Or describe your own style (Optional)
                </label>
                <input
                  id="custom_style"
                  type="text"
                  value={custom_communication_style}
                  onChange={(e) => handle_custom_style_change(e.target.value)}
                  placeholder="e.g., direct but compassionate, or using structured and analytical language..."
                  className="w-full rounded-full border border-slate-300 px-4 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              {/* Quiz Launch Card */}
              <div className="mt-2 rounded-2xl border border-indigo-100 bg-indigo-50/50 p-5 text-center">
                <h3 className="text-sm font-bold text-indigo-900">
                  Not sure which style fits you best?
                </h3>
                <p className="mt-1.5 text-xs text-indigo-700/80 max-w-md mx-auto leading-relaxed">
                  Take a quick 1-minute preference quiz and we'll recommend the communication style that best matches how you'd like Copefy to support you.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    set_quiz_active(true);
                    set_error(null);
                  }}
                  className="mt-3.5 rounded-full bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white transition-all hover:bg-indigo-700 shadow-xs active:scale-[0.98]"
                >
                  Take the Quiz
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Preference Quiz Active View */}
          {step === 2 && quiz_active && (
            <CommunicationStyleQuiz
              onComplete={handle_quiz_complete}
              onCancel={() => set_quiz_active(false)}
            />
          )}

          {/* Step 3: Goals and Context */}
          {step === 3 && (
            <div className="flex flex-col gap-5 transition-all duration-300 ease-in-out">
              {/* Wellness Goal (Required) */}
              <div>
                <label
                  htmlFor="wellness_goal"
                  className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 px-2"
                >
                  Wellness Goal <span className="text-red-500">*</span>
                </label>
                <div className="mb-2.5 px-2">
                  <p className="text-xs text-slate-700 font-medium">
                    What would you like to work on during your time with Copefy?
                  </p>
                  <p className="text-[11px] text-slate-500">
                    Think about challenges you're facing, habits you'd like to build, or goals you'd like support with.
                  </p>
                </div>
                <textarea
                  id="wellness_goal"
                  rows={4}
                  value={wellness_goal}
                  onChange={(e) => set_wellness_goal(e.target.value)}
                  placeholder="e.g., I want to build a daily mindfulness habit, reduce stress before exams, and find healthier ways to manage anxiety..."
                  className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 resize-none leading-relaxed"
                />
              </div>

              {/* Personalization Context (Optional) */}
              <div>
                <label
                  htmlFor="additional_context"
                  className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1 px-2"
                >
                  Anything you'd like the AI to keep in mind during conversations? (Optional)
                </label>
                <textarea
                  id="additional_context"
                  rows={3}
                  value={additional_context}
                  onChange={(e) => set_additional_context(e.target.value)}
                  placeholder="e.g., I prefer practical exercises over open-ended journaling, or I have a busy schedule and prefer quick tips."
                  className="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 resize-none leading-relaxed"
                />
              </div>
            </div>
          )}

          {/* Navigation Action Buttons (Hidden when Quiz is active) */}
          {!quiz_active && (
            <div className="flex gap-3 mt-4">
              {step === 1 && (
                <button
                  key="btn-skip"
                  type="button"
                  onClick={handle_skip}
                  className="flex-1 rounded-full border border-slate-300 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-all flex items-center justify-center gap-2"
                >
                  Skip
                </button>
              )}

              {step > 1 && (
                <button
                  key="btn-back"
                  type="button"
                  onClick={handle_back}
                  disabled={is_submitting}
                  className="flex-1 rounded-full border border-slate-300 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-all flex items-center justify-center gap-2"
                >
                  Back
                </button>
              )}
              
              {step < 3 ? (
                <button
                  key="btn-next"
                  type="button"
                  onClick={handle_next}
                  className="flex-1 rounded-full bg-indigo-600 py-3 text-sm font-semibold text-white hover:bg-indigo-700 transition-all flex items-center justify-center gap-2"
                >
                  Next
                </button>
              ) : (
                <button
                  key="btn-submit"
                  type="submit"
                  disabled={is_submitting}
                  className="flex-1 rounded-full bg-indigo-600 py-3 text-sm font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 transition-all flex items-center justify-center gap-2 shadow-sm"
                >
                  {is_submitting ? (
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
                      <span>Saving profile...</span>
                    </>
                  ) : (
                    "Complete Setup"
                  )}
                </button>
              )}
            </div>
          )}
        </form>
      </div>
    </div>
  );
}

export default OnboardingPage;
