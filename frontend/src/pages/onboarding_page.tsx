import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/auth_context";

const COMMUNICATION_STYLES = [
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
  const { updateProfile } = useAuth();
  const navigate = useNavigate();

  const [preferred_name, set_preferred_name] = useState("");
  const [communication_style, set_communication_style] = useState<string | null>(null);
  const [wellness_goal, set_wellness_goal] = useState("");

  const [is_submitting, set_is_submitting] = useState(false);
  const [error, set_error] = useState<string | null>(null);

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    set_error(null);

    // Validation
    if (!communication_style) {
      set_error("Please select a communication style preference.");
      return;
    }

    if (!wellness_goal.trim()) {
      set_error("Please share your wellness goal.");
      return;
    }

    set_is_submitting(true);

    try {
      await updateProfile({
        preferred_name: preferred_name.trim() || null,
        communication_style,
        wellness_goal: wellness_goal.trim(),
        onboarding_complete: true,
      });
      navigate("/", { replace: true });
    } catch (err: unknown) {
      console.error("Failed to complete onboarding:", err);
      set_error("An unexpected error occurred while saving your preferences. Please try again.");
    } finally {
      set_is_submitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12 sm:px-6 lg:px-8">
      <div className="w-full max-w-xl bg-white rounded-2xl p-8 shadow-sm ring-1 ring-slate-200">
        <div className="text-center mb-8">
          <span className="text-3xl font-extrabold tracking-tight text-indigo-600">
            Copefy
          </span>
          <h1 className="mt-3 text-2xl font-extrabold tracking-tight text-slate-900 sm:text-3xl">
            Let's personalize your experience
          </h1>
          <p className="mt-2 text-sm text-slate-500 max-w-md mx-auto">
            These answers help Copefy tailor future coaching responses to your unique personality and goals.
          </p>
        </div>

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

        <form onSubmit={handle_submit} className="flex flex-col gap-6">
          {/* Preferred Name (Optional) */}
          <div>
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
              placeholder="What should we call you?"
              className="w-full rounded-full border border-slate-300 px-4 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
            />
          </div>

          {/* Communication Style (Required Grid) */}
          <div>
            <label className="block text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2.5 px-2">
              Communication Style <span className="text-red-500">*</span>
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {COMMUNICATION_STYLES.map((style) => {
                const is_selected = communication_style === style.value;
                return (
                  <button
                    key={style.value}
                    type="button"
                    onClick={() => set_communication_style(style.value)}
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
                      <span className="absolute top-3 right-3 flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-white">
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

          {/* Wellness Goal (Required Textarea) */}
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

          {/* Submit Button */}
          <button
            type="submit"
            disabled={is_submitting}
            className="w-full shrink-0 rounded-full bg-indigo-600 py-3 text-sm font-semibold text-white transition-all hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 flex items-center justify-center gap-2 mt-2 shadow-sm"
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
                <span>Saving your profile...</span>
              </>
            ) : (
              "Complete Setup"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

export default OnboardingPage;
