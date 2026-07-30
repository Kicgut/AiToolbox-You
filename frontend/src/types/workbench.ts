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

export type RunRow = {
  id: string;
  tool: 'codex' | 'claude';
  state: string;
  mode: 'new' | 'resume' | 'fork';
  profile_id: string;
  cwd: string | null;
  model?: string | null;
  last_sequence_no: number;
  pending_approval_count?: number;
  failure_code?: string | null;
  failure_message?: string | null;
  native_session_id?: string | null;
  native_thread_id?: string | null;
  execution_path?: string;
  dispatch_state?: string;
  updated_at?: string | null;
};

export type RunEvent = {
  event_id: string;
  sequence_no: number;
  event_type: string;
  payload: Record<string, unknown>;
};

export type ApprovalRequest = {
  id: string;
  operation: string;
  target_summary: string;
  risk_level: string;
  reason: string | null;
  state: string;
  expires_at: string | null;
};

export type ComposeRunRequest = {
  action: 'new' | 'resume' | 'fork';
  tool: 'codex' | 'claude';
  profile_id: string;
  cwd: string;
  prompt: string;
  model?: string | null;
  permission_policy: Record<string, unknown>;
  budget_policy: Record<string, unknown>;
  session_copy_id?: string | null;
  client_request_id?: string;
};
