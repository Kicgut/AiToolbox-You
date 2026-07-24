import type { EventRow } from '../types/workbench';

export function pretty(value: unknown): string {
  if (!value) return '';
  return JSON.stringify(value, null, 2);
}

export function renderEventHtml(event: EventRow): string {
  const text = event.text_content || pretty(event.structured_json);
  const escaped = escapeHtml(text);
  if (event.event_type === 'file.changed' || escaped.includes('\n+') || escaped.includes('\n-')) {
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
