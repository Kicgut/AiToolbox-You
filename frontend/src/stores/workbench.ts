import { defineStore } from 'pinia';
import { api } from '../api/client';
import { FTS_NOTICE, FTS_NOTICE_VERSION } from '../constants/fts';
import type { ProfileRow, SearchStatus, SessionDetail, SessionRow, RunRow, RunEvent, ApprovalRequest, ComposeRunRequest } from '../types/workbench';

export const useWorkbenchStore = defineStore('workbench', {
  state: () => ({
    sessions: [] as SessionRow[],
    profiles: [] as ProfileRow[],
    selectedId: '',
    detail: null as SessionDetail | null,
    tool: '',
    search: '',
    loading: false,
    scanning: false,
    error: '',
    scanSummary: null as Record<string, unknown> | null,
    searchStatus: null as SearchStatus | null,
    manualTool: 'codex',
    manualRoot: '',
    virtualStart: 0,
    inspectorOpen: false
    ,runs: [] as RunRow[], activeRun: null as RunRow | null, activeApprovals: [] as ApprovalRequest[], runEvents: [] as RunEvent[], runSocket: null as WebSocket | null, runPoll: null as number | null,
    composerBusy: false, composerError: ''
  }),
  actions: {
    async init() {
      this.loading = true;
      this.error = '';
      try {
        await this.loadProfiles();
        await this.loadSearchStatus();
        await this.loadSessions();
        await this.loadRuns();
      } catch (error) {
        this.error = error instanceof Error ? error.message : '初始化失败';
        this.loading = false;
      }
    },
    async loadProfiles() {
      try {
        const payload = await api.get<{ data: ProfileRow[] }>('/api/ai-workbench/profiles');
        this.profiles = payload.data;
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载 Profile 失败';
        throw error;
      }
    },
    async loadSearchStatus() {
      try {
        this.searchStatus = await api.get<SearchStatus>('/api/ai-workbench/search/status');
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载全文索引状态失败';
        throw error;
      }
    },
    async loadSessions() {
      this.loading = true;
      this.error = '';
      try {
        const params = new URLSearchParams();
        if (this.tool) params.set('tool', this.tool);
        if (this.search) params.set('search', this.search);
        const payload = await api.get<{ data: SessionRow[] }>(`/api/ai-workbench/sessions?${params}`);
        this.sessions = payload.data;
        this.virtualStart = 0;
        if (!this.selectedId && this.sessions.length) await this.selectSession(this.sessions[0].id);
      } catch (error) {
        this.error = error instanceof Error ? error.message : '加载失败';
      } finally {
        this.loading = false;
      }
    },
    async scan() {
      this.scanning = true;
      this.error = '';
      try {
        this.scanSummary = await api.post<Record<string, unknown>>('/api/ai-workbench/scan');
        await this.loadProfiles();
        this.selectedId = '';
        this.detail = null;
        await this.loadSessions();
      } catch (error) {
        this.error = error instanceof Error ? error.message : '扫描失败';
      } finally {
        this.scanning = false;
      }
    },
    async reconcile() {
      this.scanning = true;
      this.error = '';
      try {
        this.scanSummary = await api.post<Record<string, unknown>>('/api/ai-workbench/reconcile');
        await this.loadSessions();
      } catch (error) {
        this.error = error instanceof Error ? error.message : '增量扫描失败';
      } finally {
        this.scanning = false;
      }
    },
    async addManualProfile() {
      this.error = '';
      try {
        await api.post('/api/ai-workbench/profiles/manual', {
          tool: this.manualTool,
          config_root: this.manualRoot
        });
        this.manualRoot = '';
        await this.loadProfiles();
      } catch (error) {
        this.error = error instanceof Error ? error.message : '添加目录失败';
      }
    },
    async rebuildSearch() {
      this.error = '';
      try {
        const hasCurrentConsent = this.searchStatus?.consent_state === 'user_enabled'
          && this.searchStatus.notice_version === FTS_NOTICE_VERSION;
        const needsConsent = this.searchStatus?.consent_state === 'recommended_pending'
          || this.searchStatus?.consent_state === 'user_declined'
          || (this.searchStatus?.consent_state === 'user_enabled' && !hasCurrentConsent)
          || (this.searchStatus?.consent_state === 'legacy_preserved' && !this.searchStatus.indexing_enabled);
        if (needsConsent && !(await this.confirmFtsConsent())) return;
        this.scanSummary = await api.post<Record<string, unknown>>('/api/ai-workbench/search/rebuild');
        await this.loadSearchStatus();
      } catch (error) {
        this.error = error instanceof Error ? error.message : '重建全文索引失败';
      }
    },
    async confirmFtsConsent() {
      const accepted = window.confirm(FTS_NOTICE);
      this.searchStatus = await api.post<SearchStatus>('/api/ai-workbench/search/consent', {
        decision: accepted ? 'accept' : 'decline',
        notice_version: FTS_NOTICE_VERSION
      });
      return accepted;
    },
    async toggleSearchIndexing() {
      this.error = '';
      try {
        if (this.searchStatus?.indexing_enabled) {
          this.searchStatus = await api.patch<SearchStatus>('/api/ai-workbench/search/settings', {
            indexing_enabled: false
          });
          return;
        }
        const hasCurrentConsent = this.searchStatus?.consent_state === 'user_enabled'
          && this.searchStatus.notice_version === FTS_NOTICE_VERSION;
        if (hasCurrentConsent) {
          this.searchStatus = await api.patch<SearchStatus>('/api/ai-workbench/search/settings', {
            indexing_enabled: true
          });
        } else {
          await this.confirmFtsConsent();
        }
      } catch (error) {
        this.error = error instanceof Error ? error.message : '更新全文索引设置失败';
      }
    },
    async clearSearch() {
      this.error = '';
      try {
        this.scanSummary = await api.post<Record<string, unknown>>('/api/ai-workbench/search/clear');
        await this.loadSearchStatus();
      } catch (error) {
        this.error = error instanceof Error ? error.message : '清空全文索引失败';
      }
    },
    async selectSession(id: string) {
      this.selectedId = id;
      this.detail = await api.get<SessionDetail>(`/api/ai-workbench/sessions/${id}`);
      this.inspectorOpen = true;
    },
    async loadRuns() {
      const payload = await api.get<{ data: RunRow[] }>('/api/ai-workbench/runs');
      this.runs = payload.data;
    },
    async createRun(request: ComposeRunRequest) {
      this.composerBusy = true;
      this.composerError = '';
      try {
        const payload = await api.post<{ run: RunRow }>('/api/ai-workbench/runs', request);
        await this.loadRuns();
        await this.openRun(payload.run.id);
        return payload.run;
      } catch (error) {
        this.composerError = error instanceof Error ? error.message : '无法创建运行';
        throw error;
      } finally {
        this.composerBusy = false;
      }
    },
    async openRun(id: string) {
      const payload = await api.get<{ run: RunRow; approvals: ApprovalRequest[]; events: RunEvent[] }>(`/api/ai-workbench/runs/${id}`);
      this.activeRun = payload.run;
      this.activeApprovals = payload.approvals;
      this.runEvents = payload.events;
      this.runSocket?.close();
      const socketUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/ai-workbench/runs/${id}/stream?last_sequence_no=${this.runEvents.at(-1)?.sequence_no || 0}`;
      const socket = new WebSocket(socketUrl);
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.resync_required) {
          void this.refreshActiveRun();
          return;
        }
        if (message.events) {
          const seen = new Set(this.runEvents.map(item => item.sequence_no));
          this.runEvents.push(...message.events.filter((item: RunEvent) => !seen.has(item.sequence_no)));
          this.runEvents.sort((a, b) => a.sequence_no - b.sequence_no);
          void this.refreshActiveRun();
        }
      };
      this.runSocket = socket;
      if (this.runPoll !== null) window.clearInterval(this.runPoll);
      if (['queued', 'starting', 'running', 'waiting_approval', 'cancel_requested', 'cancelling'].includes(payload.run.state)) {
        this.runPoll = window.setInterval(() => { void this.refreshActiveRun(); }, 1000);
      }
    },
    async refreshActiveRun() {
      if (!this.activeRun) return;
      const id = this.activeRun.id;
      const cursor = this.runEvents.at(-1)?.sequence_no || 0;
      const payload = await api.get<{ run: RunRow; approvals: ApprovalRequest[]; events: RunEvent[] }>(`/api/ai-workbench/runs/${id}?last_sequence_no=${cursor}`);
      if (!this.activeRun || this.activeRun.id !== id) return;
      this.activeRun = payload.run;
      this.activeApprovals = payload.approvals;
      if (payload.events.length) {
        const seen = new Set(this.runEvents.map(item => item.sequence_no));
        this.runEvents.push(...payload.events.filter(item => !seen.has(item.sequence_no)));
        this.runEvents.sort((a, b) => a.sequence_no - b.sequence_no);
      }
      await this.loadRuns();
      if (!['queued', 'starting', 'running', 'waiting_approval', 'cancel_requested', 'cancelling'].includes(payload.run.state) && this.runPoll !== null) {
        window.clearInterval(this.runPoll);
        this.runPoll = null;
      }
    },
    async cancelActiveRun() {
      if (!this.activeRun) return;
      if (!window.confirm('确认取消此运行？系统会终止该运行关联的受管进程树。')) return;
      this.activeRun = await api.post<RunRow>(`/api/ai-workbench/runs/${this.activeRun.id}/cancel`);
      await this.loadRuns();
    },
    async retryStep(stepId: string) {
      if (!this.activeRun) return;
      const payload = await api.post<{ run: RunRow }>(`/api/ai-workbench/runs/${this.activeRun.id}/retry`, { step_id: stepId });
      this.activeRun = payload.run;
      await this.loadRuns();
    },
    async decideApproval(id: string, decision: 'accept' | 'decline' | 'cancel') {
      await api.post(`/api/ai-workbench/approvals/${id}/decision`, { decision, decided_by: 'workbench-user' });
      if (this.activeRun) await this.openRun(this.activeRun.id);
    },
    closeRun() {
      this.runSocket?.close();
      this.runSocket = null;
      if (this.runPoll !== null) window.clearInterval(this.runPoll);
      this.runPoll = null;
      this.activeRun = null;
      this.activeApprovals = [];
      this.runEvents = [];
    },
    updateVirtualStart(scrollTop: number, rowHeight: number) {
      this.virtualStart = Math.max(0, Math.floor(scrollTop / rowHeight) - 5);
    }
  }
});
