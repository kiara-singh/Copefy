import React, { useState, useEffect } from "react";
import {
  CommunicationStyleType,
  QUIZ_SCENARIO,
  QUIZ_RESPONSES,
} from "../constants/quiz_constants";

interface CommunicationStyleQuizProps {
  onComplete: (recommendedStyle: CommunicationStyleType) => void;
  onCancel: () => void;
}

function shuffle_array<T>(array: T[]): T[] {
  const copy = [...array];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

export const CommunicationStyleQuiz: React.FC<CommunicationStyleQuizProps> = ({
  onComplete,
  onCancel,
}) => {
  const [quiz_round, set_quiz_round] = useState<1 | 2 | 3>(1);
  const [quiz_queue, set_quiz_queue] = useState<CommunicationStyleType[]>([]);
  const [quiz_side_flips, set_quiz_side_flips] = useState<boolean[]>([]);
  const [quiz_leader, set_quiz_leader] = useState<CommunicationStyleType | null>(null);

  useEffect(() => {
    const styles: CommunicationStyleType[] = [
      "Gentle & Supportive",
      "Motivational & Encouraging",
      "Direct & Action-Oriented",
      "Calm & Reflective",
    ];
    set_quiz_queue(shuffle_array(styles));
    set_quiz_side_flips([
      Math.random() < 0.5,
      Math.random() < 0.5,
      Math.random() < 0.5,
    ]);
  }, []);

  const handle_quiz_choice = (chosen: CommunicationStyleType) => {
    if (quiz_round === 1) {
      set_quiz_leader(chosen);
      set_quiz_round(2);
    } else if (quiz_round === 2) {
      set_quiz_leader(chosen);
      set_quiz_round(3);
    } else if (quiz_round === 3) {
      onComplete(chosen);
    }
  };

  let current_opt_a: CommunicationStyleType | null = null;
  let current_opt_b: CommunicationStyleType | null = null;

  if (quiz_queue.length === 4) {
    if (quiz_round === 1) {
      current_opt_a = quiz_queue[0];
      current_opt_b = quiz_queue[1];
    } else if (quiz_round === 2 && quiz_leader) {
      current_opt_a = quiz_leader;
      current_opt_b = quiz_queue[2];
    } else if (quiz_round === 3 && quiz_leader) {
      current_opt_a = quiz_leader;
      current_opt_b = quiz_queue[3];
    }

    if (quiz_side_flips[quiz_round - 1] && current_opt_a && current_opt_b) {
      const temp = current_opt_a;
      current_opt_a = current_opt_b;
      current_opt_b = temp;
    }
  }

  if (!current_opt_a || !current_opt_b) {
    return null;
  }

  return (
    <div className="flex flex-col gap-5 transition-all duration-300 ease-in-out">
      {/* Header Info */}
      <div className="text-center">
        <h3 className="text-lg font-bold text-slate-900">
          Communication Style Quiz
        </h3>
        <p className="mt-1 text-xs text-slate-500">
          Round {quiz_round} of 3 — Select the response you would rather receive.
        </p>
      </div>

      {/* Scenario Container */}
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider">
          Scenario
        </span>
        <p className="mt-1 text-xs text-slate-700 leading-relaxed font-medium">
          "{QUIZ_SCENARIO}"
        </p>
      </div>

      {/* Response Cards Comparison Grid */}
      <div className="grid grid-cols-1 gap-4">
        {[current_opt_a, current_opt_b].map((style_choice, idx) => (
          <div
            key={style_choice}
            className="flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-4 hover:border-indigo-400 hover:shadow-xs transition-all"
          >
            <div>
              <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                Option {idx === 0 ? "A" : "B"}
              </span>
              <p className="mt-2 text-xs text-slate-800 leading-relaxed italic">
                "{QUIZ_RESPONSES[style_choice]}"
              </p>
            </div>
            <button
              type="button"
              onClick={() => handle_quiz_choice(style_choice)}
              className="mt-4 w-full rounded-full border border-indigo-600 bg-indigo-50/50 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-600 hover:text-white transition-all"
            >
              Select This Response
            </button>
          </div>
        ))}
      </div>

      {/* Cancel Quiz Action */}
      <div className="text-center mt-1">
        <button
          type="button"
          onClick={onCancel}
          className="text-xs font-medium text-slate-500 hover:text-slate-700 underline"
        >
          Cancel Quiz and Return to Styles
        </button>
      </div>
    </div>
  );
};
