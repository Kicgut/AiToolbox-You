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
  execution_capabilities?: Record<string, unknown>;
  observed_capabilities?: { status?: string; executable?: string | null; features?: Record<string, boolean>; version?: string | null } | null;
  observed_capabilities_at?: string | null;
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
  latest_event_type?: string | null;
  latest_event_at?: string | null;
  failure_code?: string | null;
  failure_message?: string | null;
  native_session_id?: string | null;
  native_thread_id?: string | null;
  execution_path?: string;
  dispatch_state?: string;
  capabilities_snapshot_json?: string;
  budget_policy?: Record<string, unknown>;
  budget_limits?: Array<{ name: string; value: unknown; strength: 'hard' | 'provider_enforced' | 'observed_only' | 'unsupported'; availability: 'exact' | 'estimated' | 'unavailable' }>;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
};

export type RunEvent = {
  event_id: string;
  sequence_no: number;
  event_type: string;
  payload: Record<string, unknown>;
};

export type RunEventPage = {
  events: RunEvent[];
  has_more: boolean;
  next_sequence_no?: number;
  resync_required?: boolean;
};

export type ApprovalRequest = {
  id: string;
  native_request_id: string;
  operation: string;
  target_summary: string;
  risk_level: string;
  reason: string | null;
  state: string;
  expires_at: string | null;
  cwd: string | null;
  command_argv: string[];
  affected_paths: string[];
  network_targets: string[];
};

export type ComposeRunRequest = {
  action: 'new' | 'resume' | 'fork';
  tool: 'codex' | 'claude';
  profile_id: string;
  cwd: string;
  cwd_confirmed: boolean;
  prompt: string;
  model?: string | null;
  permission_policy: Record<string, unknown>;
  budget_policy: Record<string, unknown>;
  session_copy_id?: string | null;
  client_request_id?: string;
};

export type RepositoryUpdateStatus = {
  repository_available: boolean;
  checked: boolean;
  remote_known: boolean;
  update_available: boolean;
  can_apply: boolean;
  restart_required: boolean;
  auto_update_enabled: boolean;
  origin?: string;
  branch?: string;
  worktree_clean?: boolean;
  changed_file_count?: number;
  ahead?: number;
  behind?: number;
  error_code?: string | null;
  message?: string | null;
  updated?: boolean;
};
