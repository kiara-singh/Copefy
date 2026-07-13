import { useState } from "react";
import { submit_journal } from "../lib/api";

function JournalPage() {
  const [text, set_text] = useState("");
  const [is_saving, set_is_saving] = useState(false);
  const [show_success, set_show_success] = useState(false);

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || is_saving) {
      return;
    }

    set_is_saving(true);
    set_show_success(false);

    try {
      await submit_journal(trimmed);
      set_text("");
      set_show_success(true);
    } catch (error) {
      console.error("Failed to save journal entry", error);
    } finally {
      set_is_saving(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto px-6 py-8">
      <div className="mx-auto flex w-full max-w-2xl flex-col">
        <h1 className="text-2xl font-bold tracking-tight">Journal</h1>
        <p className="mt-1 text-sm text-slate-500">
          Take a moment to write about how you're feeling today.
        </p>

        <form onSubmit={handle_submit} className="mt-6 flex flex-col gap-4">
          <textarea
            value={text}
            onChange={(event) => {
              set_text(event.target.value);
              if (show_success) {
                set_show_success(false);
              }
            }}
            placeholder="How are you feeling today?"
            rows={12}
            className="w-full resize-y rounded-xl border border-slate-300 p-4 text-sm leading-relaxed outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />

          {show_success && (
            <div className="rounded-lg bg-green-50 px-4 py-2 text-sm font-medium text-green-700 ring-1 ring-green-200">
              Your journal entry has been saved.
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!text.trim() || is_saving}
              className="rounded-full bg-indigo-600 px-6 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {is_saving ? "Saving..." : "Save entry"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default JournalPage;
