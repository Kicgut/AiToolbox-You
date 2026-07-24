export type SessionRow = {
  id: string;
  tool: 'codex' | 'claude';
  native_session_id: string;
  title: string | null;
  transcript_path: string;
  updated_at: number | null;
  divergence_status: string;
  event_count: number;
  index_status: string;
};

export type EventRow = {
  id: string;
  sequence_no: number;
  event_type: string;
  role: string | null;
  text_content: string | null;
  structured_json: unknown;
  raw_json: unknown;
  data_quality: string;
};

export type SessionDetail = {
  session: SessionRow & Record<string, unknown>;
  profile: Record<string, unknown> | null;
  copies: Array<Record<string, unknown>>;
  diffSummary: Record<string, unknown>;
  events: EventRow[];
  nextEventCursor: number | null;
};

export type ProfileRow = {
  id: string;
  tool: string;
  display_name: string;
  session_root: string;
  valid: boolean;
  reason: string | null;
  indexed: boolean;
};

export type SearchStatus = {
  consent_state: 'recommended_pending' | 'user_enabled' | 'user_declined' | 'legacy_preserved';
  indexing_enabled: boolean;
  recommended: boolean;
  notice_version: number;
  indexed_events: number;
};
