import { useState } from "react";
import { submit_audio_journal, submit_journal, submit_video_journal } from "../lib/api";

function JournalPage() {
  const [text, set_text] = useState("");
  const [audio_file, set_audio_file] = useState<File | null>(null);
  const [video_file, set_video_file] = useState<File | null>(null);
  const [is_saving, set_is_saving] = useState(false);
  const [show_success, set_show_success] = useState(false);
  const [error_message, set_error_message] = useState("");

  const handle_submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = text.trim();
    if ((!trimmed && !audio_file && !video_file) || is_saving) {
      return;
    }

    set_is_saving(true);
    set_show_success(false);
    set_error_message("");

    try {
      if (audio_file) {
        const result = await submit_audio_journal(audio_file);
        if (result.status === "transcription_failed") {
          set_error_message(
            "Your audio was saved privately, but transcription failed. Nothing was added to searchable journal memory."
          );
          set_audio_file(null);
          return;
        }
        set_audio_file(null);
      }
      if (video_file) {
        const result = await submit_video_journal(video_file);
        if (result.status === "extraction_failed" || result.status === "transcription_failed") {
          set_error_message(
            "Your video was saved privately, but we could not transcribe its audio. Nothing was added to searchable journal memory."
          );
          set_video_file(null);
          return;
        }
        set_video_file(null);
      }
      if (trimmed) {
        await submit_journal(trimmed);
        set_text("");
      }
      set_show_success(true);
    } catch (error) {
      console.error("Failed to save journal entry", error);
      set_error_message("Could not save this journal entry. Please try again.");
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
              if (error_message) {
                set_error_message("");
              }
            }}
            placeholder="How are you feeling today?"
            rows={12}
            className="w-full resize-y rounded-xl border border-slate-300 p-4 text-sm leading-relaxed outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
          />

          <label className="text-sm text-slate-600">
            Or attach a short audio journal
            <input
              type="file"
              accept="audio/wav,audio/mpeg,audio/mp4,audio/webm,audio/ogg,audio/flac,.wav,.mp3,.m4a,.webm,.ogg,.flac"
              className="mt-2 block w-full text-sm"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                set_audio_file(file);
                if (show_success) {
                  set_show_success(false);
                }
                if (error_message) {
                  set_error_message("");
                }
              }}
            />
          </label>
          {audio_file && (
            <p className="text-xs text-slate-500">Selected: {audio_file.name}</p>
          )}

          <label className="text-sm text-slate-600">
            Or attach a short video journal
            <input
              type="file"
              accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm"
              className="mt-2 block w-full text-sm"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                set_video_file(file);
                if (show_success) {
                  set_show_success(false);
                }
                if (error_message) {
                  set_error_message("");
                }
              }}
            />
          </label>
          {video_file && (
            <p className="text-xs text-slate-500">Selected: {video_file.name}</p>
          )}

          {show_success && (
            <div className="rounded-lg bg-green-50 px-4 py-2 text-sm font-medium text-green-700 ring-1 ring-green-200">
              Your journal entry has been saved.
            </div>
          )}

          {error_message && (
            <div className="rounded-lg bg-red-50 px-4 py-2 text-sm font-medium text-red-700 ring-1 ring-red-200">
              {error_message}
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={(!text.trim() && !audio_file && !video_file) || is_saving}
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
