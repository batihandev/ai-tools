export type Transcript = {
  id: number;
  created_at: string;
  source: string;
  raw_text: string;
  literal_text: string;
  meta: Record<string, unknown>;
};

export type LatestResult = {
  id: number;
  raw_text: string;
  literal_text: string;
};
