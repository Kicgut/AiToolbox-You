import { defineStore } from 'pinia';
import { api } from '../api/client';
import { FTS_NOTICE, FTS_NOTICE_VERSION } from '../constants/fts';
import type { ProfileRow, SearchStatus, SessionDetail, SessionRow } from '../types/workbench';

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
  }),
  actions: {
    async init() {
      this.loading = true;
      this.error = '';
      try {
        await this.loadProfiles();
        await this.loadSearchStatus();
        await this.loadSessions();
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
    updateVirtualStart(scrollTop: number, rowHeight: number) {
      this.virtualStart = Math.max(0, Math.floor(scrollTop / rowHeight) - 5);
    }
  }
});
