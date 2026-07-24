import { createApp, defineComponent } from 'vue';
import { createPinia, defineStore } from 'pinia';
import { createRouter, createWebHistory } from 'vue-router';
import './styles.css';

type SessionRow = {
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

type EventRow = {
  id: string;
  sequence_no: number;
  event_type: string;
  role: string | null;
  text_content: string | null;
  structured_json: unknown;
  raw_json: unknown;
  data_quality: string;
};

type SessionDetail = {
  session: SessionRow & Record<string, unknown>;
  profile: Record<string, unknown> | null;
  copies: Array<Record<string, unknown>>;
  diffSummary: Record<string, unknown>;
  events: EventRow[];
  nextEventCursor: number | null;
};

type ProfileRow = {
  id: string;
  tool: string;
  display_name: string;
  session_root: string;
  valid: boolean;
  reason: string | null;
  indexed: boolean;
};

type SearchStatus = {
  enabled: boolean;
  indexed_events: number;
};

const api = {
  async get<T>(url: string): Promise<T> {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  },
  async post<T>(url: string, body?: unknown): Promise<T> {
    const response = await fetch(url, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }
};

const useWorkbenchStore = defineStore('workbench', {
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
    async loadProfiles() {
      const payload = await api.get<{ data: ProfileRow[] }>('/api/ai-workbench/profiles');
      this.profiles = payload.data;
    },
    async loadSearchStatus() {
      this.searchStatus = await api.get<SearchStatus>('/api/ai-workbench/search/status');
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
      this.scanSummary = await api.post<Record<string, unknown>>('/api/ai-workbench/search/rebuild');
      await this.loadSearchStatus();
    },
    async clearSearch() {
      this.scanSummary = await api.post<Record<string, unknown>>('/api/ai-workbench/search/clear');
      await this.loadSearchStatus();
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

const SessionCenter = defineComponent({
  setup() {
    const store = useWorkbenchStore();
    store.loadProfiles().then(() => store.loadSearchStatus()).then(() => store.loadSessions());
    return { store };
  },
  computed: {
    visibleSessions(): SessionRow[] {
      return this.store.sessions.slice(this.store.virtualStart, this.store.virtualStart + 70);
    },
    topSpacer(): string {
      return `${this.store.virtualStart * 86}px`;
    },
    bottomSpacer(): string {
      const hidden = Math.max(0, this.store.sessions.length - this.store.virtualStart - 70);
      return `${hidden * 86}px`;
    }
  },
  methods: {
    formatTime(value: number | null) {
      if (!value) return '—';
      return new Date(value * 1000).toLocaleString();
    },
    pretty(value: unknown) {
      if (!value) return '';
      return JSON.stringify(value, null, 2);
    },
    renderText(event: EventRow) {
      const text = event.text_content || this.pretty(event.structured_json);
      return renderEventHtml(text, event.event_type);
    },
    onSessionScroll(event: Event) {
      const target = event.target as HTMLElement;
      this.store.updateVirtualStart(target.scrollTop, 86);
    }
  },
  template: `
    <main class="workspace">
      <aside class="sessions-pane">
        <div class="toolbar">
          <select v-model="store.tool" @change="store.loadSessions" aria-label="工具筛选">
            <option value="">全部工具</option>
            <option value="codex">Codex</option>
            <option value="claude">Claude</option>
          </select>
          <button @click="store.scan" :disabled="store.scanning">{{ store.scanning ? '扫描中' : '扫描' }}</button>
        </div>
        <button class="secondary" @click="store.reconcile" :disabled="store.scanning">增量扫描</button>
        <input class="search" v-model="store.search" @keydown.enter="store.loadSessions" placeholder="搜索标题、路径或 Session ID" />
        <button class="secondary" @click="store.loadSessions">应用筛选</button>

        <div class="manual-profile">
          <select v-model="store.manualTool" aria-label="手动目录工具">
            <option value="codex">Codex</option>
            <option value="claude">Claude</option>
          </select>
          <input v-model="store.manualRoot" placeholder="添加配置根目录" />
          <button class="secondary" @click="store.addManualProfile">添加</button>
        </div>

        <div v-if="store.error" class="notice error">{{ store.error }}</div>
        <div v-if="store.scanSummary" class="notice">
          {{ pretty(store.scanSummary) }}
        </div>
        <div class="notice search-controls">
          <span>全文索引 {{ store.searchStatus?.enabled ? '已开启' : '关闭' }} · {{ store.searchStatus?.indexed_events || 0 }} 条</span>
          <button class="mini" @click="store.rebuildSearch">重建</button>
          <button class="mini quiet" @click="store.clearSearch">清空</button>
        </div>

        <section class="profile-strip">
          <div v-for="profile in store.profiles" :key="profile.id" class="profile-row" :class="{ bad: !profile.valid }">
            <span>{{ profile.tool }}</span>
            <small>{{ profile.valid ? '可用' : profile.reason }}</small>
          </div>
        </section>

        <div class="session-list" aria-live="polite" @scroll="onSessionScroll">
          <div v-if="store.loading" class="empty">加载会话中</div>
          <div :style="{ height: topSpacer }"></div>
          <button
            v-for="session in visibleSessions"
            :key="session.id"
            class="session-item"
            :class="{ selected: session.id === store.selectedId }"
            @click="store.selectSession(session.id)"
          >
            <span class="session-title">{{ session.title || session.native_session_id }}</span>
            <span class="session-meta">{{ session.tool }} · {{ session.event_count }} events</span>
            <span class="session-path">{{ session.transcript_path }}</span>
          </button>
          <div :style="{ height: bottomSpacer }"></div>
          <div v-if="!store.loading && !store.sessions.length" class="empty">
            没有已索引会话。先点击扫描，或确认 Codex/Claude 默认目录存在。
          </div>
        </div>
      </aside>

      <section class="timeline-pane">
        <div v-if="!store.detail" class="empty center">选择一个会话查看时间线</div>
        <template v-else>
          <div class="timeline-header">
            <div>
              <h2>{{ store.detail.session.title || store.detail.session.native_session_id }}</h2>
              <p>{{ store.detail.session.tool }} · {{ formatTime(store.detail.session.updated_at) }}</p>
            </div>
            <span class="badge">{{ store.detail.session.divergence_status }}</span>
            <button class="secondary inspector-toggle" @click="store.inspectorOpen = !store.inspectorOpen">检查器</button>
          </div>
          <div class="timeline">
            <article v-for="event in store.detail.events" :key="event.id" class="event" :data-type="event.event_type">
              <header>
                <span>{{ event.sequence_no }} · {{ event.event_type }}</span>
                <strong>{{ event.role || event.data_quality }}</strong>
              </header>
              <div class="event-body" v-html="renderText(event)"></div>
              <details v-if="event.raw_json">
                <summary>Raw</summary>
                <pre>{{ pretty(event.raw_json) }}</pre>
              </details>
            </article>
          </div>
        </template>
      </section>

      <aside class="inspector-pane" :class="{ open: store.inspectorOpen }">
        <h2>检查器</h2>
        <template v-if="store.detail">
          <dl>
            <dt>Session ID</dt><dd>{{ store.detail.session.native_session_id }}</dd>
            <dt>索引状态</dt><dd>{{ store.detail.session.index_status }}</dd>
            <dt>事件数</dt><dd>{{ store.detail.session.event_count }}</dd>
            <dt>Profile</dt><dd>{{ store.detail.profile?.display_name || store.detail.session.profile_id }}</dd>
            <dt>Transcript</dt><dd>{{ store.detail.session.transcript_path }}</dd>
          </dl>
          <h3>副本</h3>
          <div v-for="copy in store.detail.copies" :key="copy.id as string" class="copy-row">
            <span>{{ copy.divergence_status }}</span>
            <small>{{ copy.event_count }} events</small>
          </div>
          <h3>差异摘要</h3>
          <pre>{{ pretty(store.detail.diffSummary) }}</pre>
        </template>
        <div v-else class="empty">会话元数据会显示在这里。</div>
      </aside>
    </main>
  `
});

function renderEventHtml(text: string, eventType: string): string {
  const escaped = escapeHtml(text);
  if (eventType === 'file.changed' || escaped.includes('\n+') || escaped.includes('\n-')) {
    return `<pre class="diff">${escaped
      .split('\n')
      .map((line) => {
        const klass = line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : '';
        return `<span class="${klass}">${line}</span>`;
      })
      .join('\n')}</pre>`;
  }
  const withCode = escaped.replace(/```([\\s\\S]*?)```/g, '<pre><code>$1</code></pre>');
  return withCode.replace(/\n/g, '<br />');
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => {
    const map: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
    return map[char];
  });
}

const AppShell = defineComponent({
  template: `
    <div class="shell">
      <header class="topbar">
        <div>
          <h1>AI 编程工作台</h1>
          <p>只读统一会话中心</p>
        </div>
        <nav>
          <a href="/">代理流量</a>
          <RouterLink to="/workbench" class="active">会话</RouterLink>
        </nav>
      </header>
      <RouterView />
    </div>
  `
});

const router = createRouter({
  history: createWebHistory(),
  routes: [{ path: '/workbench', component: SessionCenter }]
});

createApp(AppShell).use(createPinia()).use(router).mount('#app');
