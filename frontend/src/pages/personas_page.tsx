import React, { useEffect, useState } from "react";
import {
  AIPersona,
  PersonaPayload,
  create_persona,
  delete_persona,
  get_personas,
  update_persona,
} from "../lib/api";

const ROLE_PRESETS = ["Friend", "Parent", "Sibling", "Mentor", "Coach"];
const PERSONALITY_TRAITS = [
  "Supportive",
  "Direct",
  "Calm",
  "Humorous",
  "Motivational",
  "Reflective",
];

function PersonasPage() {
  const [personas, set_personas] = useState<AIPersona[]>([]);
  const [loading, set_loading] = useState(true);
  const [error, set_error] = useState<string | null>(null);

  // Modal State
  const [is_modal_open, set_is_modal_open] = useState(false);
  const [editing_persona, set_editing_persona] = useState<AIPersona | null>(null);

  // Form Fields
  const [name, set_name] = useState("");
  const [role_type, set_role_type] = useState("");
  const [base_personality, set_base_personality] = useState("");
  const [custom_instructions, set_custom_instructions] = useState("");
  const [form_error, set_form_error] = useState<string | null>(null);
  const [is_submitting, set_is_submitting] = useState(false);

  // Delete Confirmation State
  const [deleting_persona, set_deleting_persona] = useState<AIPersona | null>(null);
  const [is_deleting, set_is_deleting] = useState(false);

  const fetch_personas = async () => {
    set_loading(true);
    set_error(null);
    try {
      const data = await get_personas();
      set_personas(data);
    } catch (err) {
      console.error("Failed to load personas:", err);
      set_error("Failed to load personas. Please try again.");
    } finally {
      set_loading(false);
    }
  };

  useEffect(() => {
    fetch_personas();
  }, []);

  const open_create_modal = () => {
    set_editing_persona(null);
    set_name("");
    set_role_type("");
    set_base_personality("");
    set_custom_instructions("");
    set_form_error(null);
    set_is_modal_open(true);
  };

  const open_edit_modal = (persona: AIPersona) => {
    set_editing_persona(persona);
    set_name(persona.name);
    set_role_type(persona.role_type);
    set_base_personality(persona.base_personality);
    set_custom_instructions(persona.custom_instructions || "");
    set_form_error(null);
    set_is_modal_open(true);
  };

  const close_modal = () => {
    if (!is_submitting) {
      set_is_modal_open(false);
      set_editing_persona(null);
    }
  };

  const handle_role_preset_click = (preset: string) => {
    set_role_type(preset);
  };

  const handle_trait_toggle = (trait: string) => {
    const current_traits = base_personality
      ? base_personality.split(",").map((t) => t.trim()).filter(Boolean)
      : [];

    if (current_traits.includes(trait)) {
      const updated = current_traits.filter((t) => t !== trait);
      set_base_personality(updated.join(", "));
    } else {
      const updated = [...current_traits, trait];
      set_base_personality(updated.join(", "));
    }
  };

  const handle_submit = async (e: React.FormEvent) => {
    e.preventDefault();
    set_form_error(null);

    const trimmed_name = name.trim();
    const trimmed_role = role_type.trim();
    const trimmed_personality = base_personality.trim();
    const trimmed_instructions = custom_instructions.trim();

    if (!trimmed_name) {
      set_form_error("Persona name is required.");
      return;
    }
    if (!trimmed_role) {
      set_form_error("Role is required.");
      return;
    }
    if (!trimmed_personality) {
      set_form_error("Personality description is required.");
      return;
    }

    set_is_submitting(true);
    const payload: PersonaPayload = {
      name: trimmed_name,
      role_type: trimmed_role,
      base_personality: trimmed_personality,
      custom_instructions: trimmed_instructions,
    };

    try {
      if (editing_persona) {
        const updated = await update_persona(editing_persona.id, payload);
        set_personas((prev) =>
          prev.map((p) => (p.id === updated.id ? updated : p))
        );
      } else {
        const created = await create_persona(payload);
        set_personas((prev) => [created, ...prev]);
      }
      set_is_modal_open(false);
      set_editing_persona(null);
    } catch (err) {
      console.error("Failed to save persona:", err);
      set_form_error("Failed to save persona. Please check your inputs and try again.");
    } finally {
      set_is_submitting(false);
    }
  };

  const handle_confirm_delete = async () => {
    if (!deleting_persona || is_deleting) return;

    set_is_deleting(true);
    try {
      await delete_persona(deleting_persona.id);
      set_personas((prev) => prev.filter((p) => p.id !== deleting_persona.id));
      set_deleting_persona(null);
    } catch (err) {
      console.error("Failed to delete persona:", err);
      alert("Failed to delete persona. Please try again.");
    } finally {
      set_is_deleting(false);
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50">
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">
            Personas
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Configure custom AI roles and personalities for your conversations.
          </p>
        </div>
        <button
          type="button"
          onClick={open_create_modal}
          className="rounded-full bg-indigo-600 px-4 py-2 text-xs font-semibold text-white transition-all hover:bg-indigo-700 shadow-xs flex items-center gap-1.5"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M12 4v16m8-8H4"
            />
          </svg>
          <span>Create Persona</span>
        </button>
      </header>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-5xl">
          {error && (
            <div className="mb-6 rounded-xl border border-red-100 bg-red-50 p-4 text-sm text-red-600">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex h-64 items-center justify-center">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent"></div>
            </div>
          ) : personas.length === 0 ? (
            /* Empty State */
            <div className="mt-12 flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center shadow-xs">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50 text-indigo-600 mb-3">
                <svg
                  className="h-6 w-6"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="1.75"
                    d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"
                  />
                  <circle cx="12" cy="7" r="4" />
                </svg>
              </div>
              <h3 className="text-base font-bold text-slate-900">
                No personas created yet
              </h3>
              <p className="mt-1 max-w-sm text-xs text-slate-500">
                Create a custom persona to define specific roles, traits, and guidelines for your AI companion.
              </p>
              <button
                type="button"
                onClick={open_create_modal}
                className="mt-5 rounded-full bg-indigo-600 px-5 py-2.5 text-xs font-semibold text-white transition-all hover:bg-indigo-700 shadow-xs"
              >
                Create Your First Persona
              </button>
            </div>
          ) : (
            /* Personas Cards Grid */
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
              {personas.map((persona) => (
                <div
                  key={persona.id}
                  className="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-xs transition-all hover:shadow-md"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <h3 className="text-base font-bold text-slate-900 truncate">
                        {persona.name}
                      </h3>
                      <span className="shrink-0 rounded-full bg-indigo-50 px-2.5 py-0.5 text-[10px] font-bold text-indigo-700 uppercase tracking-wider">
                        {persona.role_type}
                      </span>
                    </div>

                    <div className="mt-3">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Personality
                      </span>
                      <p className="mt-0.5 text-xs font-medium text-slate-700 leading-relaxed">
                        {persona.base_personality}
                      </p>
                    </div>

                    {persona.custom_instructions && (
                      <div className="mt-3">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                          Instructions Preview
                        </span>
                        <p className="mt-0.5 text-xs italic text-slate-500 line-clamp-2 leading-relaxed">
                          "{persona.custom_instructions}"
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="mt-5 flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
                    <button
                      type="button"
                      onClick={() => open_edit_modal(persona)}
                      className="rounded-lg px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100 hover:text-slate-900 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => set_deleting_persona(persona)}
                      className="rounded-lg px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* CREATE / EDIT MODAL */}
      {is_modal_open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-xs">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl ring-1 ring-slate-200">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold text-slate-900">
                {editing_persona ? "Edit Persona" : "Create Persona"}
              </h2>
              <button
                type="button"
                onClick={close_modal}
                disabled={is_submitting}
                className="text-slate-400 hover:text-slate-600"
              >
                ✕
              </button>
            </div>

            {form_error && (
              <div className="mb-4 rounded-xl border border-red-100 bg-red-50 p-3 text-xs text-red-600">
                {form_error}
              </div>
            )}

            <form onSubmit={handle_submit} className="flex flex-col gap-4">
              {/* Persona Name */}
              <div>
                <label
                  htmlFor="persona_name"
                  className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1"
                >
                  Persona Name <span className="text-red-500">*</span>
                </label>
                <input
                  id="persona_name"
                  type="text"
                  required
                  value={name}
                  onChange={(e) => set_name(e.target.value)}
                  placeholder="e.g., Alex, Mom, Mentor..."
                  className="w-full rounded-xl border border-slate-300 px-3.5 py-2 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              {/* Role */}
              <div>
                <label
                  htmlFor="persona_role"
                  className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1"
                >
                  Role / Relationship <span className="text-red-500">*</span>
                </label>
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {ROLE_PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      onClick={() => handle_role_preset_click(preset)}
                      className={`rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ${
                        role_type === preset
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}
                    >
                      {preset}
                    </button>
                  ))}
                </div>
                <input
                  id="persona_role"
                  type="text"
                  required
                  value={role_type}
                  onChange={(e) => set_role_type(e.target.value)}
                  placeholder="Or enter custom role (e.g., Best Friend, Fitness Coach)..."
                  className="w-full rounded-xl border border-slate-300 px-3.5 py-2 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              {/* Personality */}
              <div>
                <label
                  htmlFor="persona_personality"
                  className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1"
                >
                  Personality Traits <span className="text-red-500">*</span>
                </label>
                <div className="mb-2 flex flex-wrap gap-1.5">
                  {PERSONALITY_TRAITS.map((trait) => {
                    const active_traits = base_personality
                      ? base_personality.split(",").map((t) => t.trim())
                      : [];
                    const is_active = active_traits.includes(trait);
                    return (
                      <button
                        key={trait}
                        type="button"
                        onClick={() => handle_trait_toggle(trait)}
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ${
                          is_active
                            ? "bg-indigo-600 text-white"
                            : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                        }`}
                      >
                        {trait} {is_active ? "✓" : "+"}
                      </button>
                    );
                  })}
                </div>
                <input
                  id="persona_personality"
                  type="text"
                  required
                  value={base_personality}
                  onChange={(e) => set_base_personality(e.target.value)}
                  placeholder="e.g., Supportive, humorous, and patient..."
                  className="w-full rounded-xl border border-slate-300 px-3.5 py-2 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              {/* Custom Instructions */}
              <div>
                <label
                  htmlFor="persona_instructions"
                  className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1"
                >
                  Custom Instructions (Optional)
                </label>
                <textarea
                  id="persona_instructions"
                  rows={3}
                  value={custom_instructions}
                  onChange={(e) => set_custom_instructions(e.target.value)}
                  placeholder="e.g., Talk to me like a close friend who knows me well. Be encouraging, but call me out if I am overthinking..."
                  className="w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm outline-none transition-all focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 resize-none leading-relaxed"
                />
              </div>

              {/* Actions */}
              <div className="mt-2 flex items-center justify-end gap-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={close_modal}
                  disabled={is_submitting}
                  className="rounded-full px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={is_submitting}
                  className="rounded-full bg-indigo-600 px-5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-all shadow-xs"
                >
                  {is_submitting
                    ? "Saving..."
                    : editing_persona
                    ? "Save Changes"
                    : "Create Persona"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* DELETE CONFIRMATION MODAL */}
      {deleting_persona && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl ring-1 ring-slate-200">
            <h3 className="text-base font-bold text-slate-900">
              Delete "{deleting_persona.name}"?
            </h3>
            <p className="mt-1 text-xs text-slate-500 leading-relaxed">
              Are you sure you want to delete this persona? This action cannot be undone.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => set_deleting_persona(null)}
                disabled={is_deleting}
                className="rounded-full px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handle_confirm_delete}
                disabled={is_deleting}
                className="rounded-full bg-red-600 px-5 py-2 text-xs font-semibold text-white hover:bg-red-700 disabled:opacity-50 transition-colors shadow-xs"
              >
                {is_deleting ? "Deleting..." : "Delete Persona"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default PersonasPage;
