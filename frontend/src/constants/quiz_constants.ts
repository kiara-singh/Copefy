export type CommunicationStyleType =
  | "Gentle & Supportive"
  | "Motivational & Encouraging"
  | "Direct & Action-Oriented"
  | "Calm & Reflective";

export const QUIZ_SCENARIO =
  "You have an important presentation at work or school tomorrow and you're feeling overwhelmed, anxious, and underprepared.";

export const QUIZ_RESPONSES: Record<CommunicationStyleType, string> = {
  "Gentle & Supportive":
    "It's completely normal to feel nervous before something big. Take a soft breath—you've prepared more than you realize, and it's okay to feel this way. How can I help comfort or support you right now?",
  "Motivational & Encouraging":
    "You've got this! Nerves just mean you care about doing awesome. Channel that energy into your performance—you are fully capable of knocking this presentation out of the park!",
  "Direct & Action-Oriented":
    "Let me give you 3 practical steps right now: 1) Outline your top 3 main points. 2) Practice your opening out loud twice. 3) Get a good night's sleep. Ready to start on point 1?",
  "Calm & Reflective":
    "Take a pause and notice where you're holding tension right now. When you look deeper at this feeling of being overwhelmed, what is the core thought or fear underneath it?",
};
