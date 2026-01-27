export type PhoneIssue = {
  phone: string;
  score: number;
  alt?: string;
  alt_score?: number;
};

export type WordScore = {
  word: string;
  start: number;
  end: number;
  score: number;
  risk: "low" | "medium" | "high";
  issues: PhoneIssue[];
  expected_phonemes?: string[];
  fluency_score?: number;
};

export type ProsodyOut = {
  pitch_mean: number;
  pitch_std: number;
  intensity_mean: number;
  speaking_rate: number;
};

export type PronScoreOut = {
  overall_score: number;
  overall_risk: string;
  overall_fluency?: number;
  prosody?: ProsodyOut | null;
  words: WordScore[];
};

export type Transcript = {
  id: number;
  created_at: string;
  source: string;
  raw_text: string;
  literal_text: string;
  meta: Record<string, unknown> & { pronunciation?: PronScoreOut };
};

export type LatestResult = {
  id: number;
  raw_text: string;
  literal_text: string;
  pronunciation?: PronScoreOut;
};

export type OllamaHealth = {
  ollama_status: "online" | "offline" | "error";
  ollama_url: string;
};
