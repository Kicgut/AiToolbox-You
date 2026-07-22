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

const api = {
  async get<T>(url: string): Promise<T> {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  },
  async post<T>(url: string): Promise<T> {
    const response = await fetch(url, { method: 'POST' });
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
    scanSummary: null as Record<string, unknown> | null
  }),
  actions: {
    async loadProfiles() {
      const payload = await api.get<{ data: ProfileRow[] }>('/api/ai-workbench/profiles');
      this.profiles = payload.data;
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
    async selectSession(id: string) {
      this.selectedId = id;
      this.detail = await api.get<SessionDetail>(`/api/ai-workbench/sessions/${id}`);
    }
  }
});

const SessionCenter = defineComponent({
  setup() {
    const store = useWorkbenchStore();
    store.loadProfiles().then(() => store.loadSessions());
    return { store };
  },
  methods: {
    formatTime(value: number | null) {
      if (!value) return '—';
      return new Date(value * 1000).toLocaleString();
    },
    pretty(value: unknown) {
      if (!value) return '';
      return JSON.stringify(value, null, 2);
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
        <input class="search" v-model="store.search" @keydown.enter="store.loadSessions" placeholder="搜索标题、路径或 Session ID" />
        <button class="secondary" @click="store.loadSessions">应用筛选</button>

        <div v-if="store.error" class="notice error">{{ store.error }}</div>
        <div v-if="store.scanSummary" class="notice">
          索引 {{ store.scanSummary.sessions_indexed }} 个会话，{{ store.scanSummary.events_indexed }} 条事件
        </div>
        <div class="notice">全文索引默认关闭；当前搜索覆盖标题、路径和 Session ID。</div>

        <section class="profile-strip">
          <div v-for="profile in store.profiles" :key="profile.id" class="profile-row" :class="{ bad: !profile.valid }">
            <span>{{ profile.tool }}</span>
            <small>{{ profile.valid ? '可用' : profile.reason }}</small>
          </div>
        </section>

        <div class="session-list" aria-live="polite">
          <div v-if="store.loading" class="empty">加载会话中</div>
          <button
            v-for="session in store.sessions"
            :key="session.id"
            class="session-item"
            :class="{ selected: session.id === store.selectedId }"
            @click="store.selectSession(session.id)"
          >
            <span class="session-title">{{ session.title || session.native_session_id }}</span>
            <span class="session-meta">{{ session.tool }} · {{ session.event_count }} events</span>
            <span class="session-path">{{ session.transcript_path }}</span>
          </button>
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
          </div>
          <div class="timeline">
            <article v-for="event in store.detail.events" :key="event.id" class="event" :data-type="event.event_type">
              <header>
                <span>{{ event.sequence_no }} · {{ event.event_type }}</span>
                <strong>{{ event.role || event.data_quality }}</strong>
              </header>
              <p v-if="event.text_content">{{ event.text_content }}</p>
              <pre v-else-if="event.structured_json">{{ pretty(event.structured_json) }}</pre>
              <details v-if="event.raw_json">
                <summary>Raw</summary>
                <pre>{{ pretty(event.raw_json) }}</pre>
              </details>
            </article>
          </div>
        </template>
      </section>

      <aside class="inspector-pane">
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
        </template>
        <div v-else class="empty">会话元数据会显示在这里。</div>
      </aside>
    </main>
  `
});

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

