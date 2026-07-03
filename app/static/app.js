let liveWS;
let liveData = [];
let sortKey = 'start_ts';
let sortAsc = true;
let chart;

function connectLiveWS() {
    liveWS = new WebSocket(`ws://${location.host}/ws/live`);
    liveWS.onmessage = (e) => {
        liveData = JSON.parse(e.data);
        renderLiveTable(liveData);
    };
    liveWS.onclose = () => setTimeout(connectLiveWS, 2000);
    liveWS.onerror = () => liveWS.close();
}

function renderLiveTable(data) {
    const direction = document.getElementById('live-direction').value;
    if (direction) {
        data = data.filter(c => c.direction === direction);
    }
    data.sort((a, b) => {
        const va = a[sortKey];
        const vb = b[sortKey];
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
    });
    const table = document.getElementById('live-table');
    if (!table.tHead.innerHTML) {
        const headers = ['process_name', 'host', 'dest_port', 'network', 'direction', 'chain', 'rule', 'speed_up', 'speed_down', 'total_up', 'total_down', 'start_ts'];
        const tr = document.createElement('tr');
        headers.forEach(h => {
            const th = document.createElement('th');
            th.textContent = h;
            th.onclick = () => {
                if (sortKey === h) {
                    sortAsc = !sortAsc;
                } else {
                    sortKey = h;
                    sortAsc = true;
                }
                renderLiveTable(liveData);
            };
            tr.appendChild(th);
        });
        table.tHead.appendChild(tr);
    }
    const tbody = table.tBodies[0];
    tbody.innerHTML = '';
    data.forEach(c => {
        const tr = document.createElement('tr');
        tr.className = c.direction;
        const fields = ['process_name', 'host', 'dest_port', 'network', 'direction', 'chain', 'rule', 'speed_up', 'speed_down', 'total_up', 'total_down', 'start_ts'];
        fields.forEach(f => {
            const td = document.createElement('td');
            td.textContent = c[f];
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

async function fetchTimeseries(granularity = 'hour', range = '', direction = '', app = '') {
    const params = new URLSearchParams({ granularity });
    if (direction) params.set('direction', direction);
    if (app) params.set('app', app);
    const res = await fetch(`/api/timeseries?${params.toString()}`);
    const data = await res.json();
    renderChart(data.buckets);
    return data.buckets;
}

function renderChart(buckets) {
    const labels = buckets.map(b => new Date(b.bucket * 1000).toLocaleString());
    const directUp = buckets.map(b => b.direct_upload);
    const directDown = buckets.map(b => b.direct_download);
    const proxyUp = buckets.map(b => b.proxy_upload);
    const proxyDown = buckets.map(b => b.proxy_download);
    const datasets = [
        { label: '直连上传', data: directUp, backgroundColor: 'rgba(75,192,192,0.5)' },
        { label: '直连下载', data: directDown, backgroundColor: 'rgba(75,192,192,0.9)' },
        { label: '代理上传', data: proxyUp, backgroundColor: 'rgba(255,99,132,0.5)' },
        { label: '代理下载', data: proxyDown, backgroundColor: 'rgba(255,99,132,0.9)' },
    ];
    if (chart) {
        chart.data.labels = labels;
        chart.data.datasets = datasets;
        chart.update();
        return;
    }
    const ctx = document.getElementById('trafficChart').getContext('2d');
    chart = new Chart(ctx, {
        type: 'bar',
        data: { labels, datasets },
        options: {
            responsive: true,
            scales: {
                x: { stacked: true },
                y: { stacked: true, beginAtZero: true },
            },
        },
    });
}

async function fetchTop(dimension = 'app', range = '1h', direction = '', sort = 'total') {
    const params = new URLSearchParams({ dimension, range, sort, limit: 20 });
    if (direction) params.set('direction', direction);
    const res = await fetch(`/api/top?${params.toString()}`);
    const data = await res.json();
    renderTopTable(data.data, dimension);
    return data.data;
}

function renderTopTable(data, dimension) {
    const table = document.getElementById('top-table');
    table.tHead.innerHTML = '';
    table.tBodies[0].innerHTML = '';
    if (!data.length) return;
    const headers = Object.keys(data[0]);
    const tr = document.createElement('tr');
    headers.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        tr.appendChild(th);
    });
    table.tHead.appendChild(tr);
    const tbody = table.tBodies[0];
    data.forEach(row => {
        const tr = document.createElement('tr');
        headers.forEach(h => {
            const td = document.createElement('td');
            td.textContent = row[h];
            if (h === 'process_name' || h === 'host') {
                td.style.cursor = 'pointer';
                td.onclick = () => {
                    document.getElementById('live-direction').value = row.direction || '';
                    renderLiveTable(liveData.filter(c => c.process_name === row.process_name || c.host === row.host));
                };
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

function exportCSV(endpoint, params) {
    const url = new URL(`/api/${endpoint}`, location.origin);
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== '') url.searchParams.set(k, v);
    });
    window.open(url.toString(), '_blank');
}

async function pollStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        document.getElementById('status-indicator').className = data.connected ? 'dot connected' : 'dot';
        document.getElementById('status-text').textContent = data.connected ? `已连接 (${data.live_count})` : '未连接';
    } catch {}
}

document.addEventListener('DOMContentLoaded', () => {
    connectLiveWS();
    fetchTimeseries();
    fetchTop();
    setInterval(pollStatus, 5000);
    pollStatus();
    document.querySelectorAll('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            fetchTimeseries(btn.dataset.granularity);
        });
    });
    document.getElementById('live-direction').addEventListener('change', () => renderLiveTable(liveData));
    document.getElementById('top-dimension').addEventListener('change', () => fetchTop(document.getElementById('top-dimension').value, document.getElementById('top-range').value, document.getElementById('top-direction').value, document.getElementById('top-sort').value));
    document.getElementById('top-range').addEventListener('change', () => fetchTop());
    document.getElementById('top-direction').addEventListener('change', () => fetchTop());
    document.getElementById('top-sort').addEventListener('change', () => fetchTop());
    document.getElementById('btn-export-top').addEventListener('click', () => {
        exportCSV('export', {
            kind: 'top',
            dimension: document.getElementById('top-dimension').value,
            range: document.getElementById('top-range').value,
            direction: document.getElementById('top-direction').value,
            sort: document.getElementById('top-sort').value,
            limit: 100,
        });
    });
});
