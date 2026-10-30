/**
 * TERMIQ Desktop Workspace Application V2.1
 * Communicates with the local FastAPI backend (http://127.0.0.1:8765)
 */

const API_BASE = window.location.origin;

let activeView = 'home';
let explanationMode = 'beginner'; // 'beginner' | 'advanced'
let refreshTimer = null;
let currentBuilderTask = null;
let currentEditingPath = null;

// ── API Helpers ────────────────────────────────────────────────────────

async function api(path, options = {}) {
    const defaultHeaders = { 'Content-Type': 'application/json' };
    const config = {
        ...options,
        headers: { ...defaultHeaders, ...(options.headers || {}) },
    };
    if (options.body && typeof options.body === 'object') {
        config.body = JSON.stringify(options.body);
    }
    try {
        const resp = await fetch(`${API_BASE}${path}`, config);
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
        }
        return data;
    } catch (err) {
        console.error(`API Error ${path}:`, err);
        throw err;
    }
}

// ── Navigation & View Switching ────────────────────────────────────────

function switchView(viewId) {
    activeView = viewId;
    document.querySelectorAll('.nav-item').forEach(el => {
        el.classList.toggle('active', el.dataset.view === viewId);
    });
    document.querySelectorAll('.view-section').forEach(el => {
        el.classList.toggle('active', el.id === `view-${viewId}`);
    });

    const titles = {
        home: 'Home Overview',
        assistant: 'AI Natural-Language Assistant',
        files: 'File & Folder Copilot',
        monitor: 'Linux System Monitor',
        diagnostics: 'System Diagnostics',
        developer: 'Developer Tools',
        builder: 'Project Builder',
        automation: 'Automation Center',
        history: 'Task & Workflow History',
        notifications: 'Notification Center',
        security: 'Security, Permissions & Audit Trail',
        settings: 'Application Settings',
    };
    document.getElementById('topbarTitle').textContent = titles[viewId] || 'TERMIQ';

    // Trigger on-demand view loads
    if (viewId === 'monitor') loadMonitorData();
    if (viewId === 'files') loadFileRoots();
    if (viewId === 'automation') loadAutomationWorkflows();
    if (viewId === 'history') loadTaskHistory();
    if (viewId === 'notifications') loadNotifications();
    if (viewId === 'security') loadSecurityAudit();
    if (viewId === 'settings') loadSettings();
}

// ── Live Home Stats ───────────────────────────────────────────────────

async function refreshHomeData() {
    try {
        const summary = await api('/api/v1/system/summary');
        document.getElementById('backendStatusDot').className = 'status-dot';
        document.getElementById('backendStatusText').textContent = 'Connected';

        // CPU
        const cpuPct = summary.cpu.usage_percent;
        document.getElementById('homeCpuVal').textContent = `${cpuPct}%`;
        document.getElementById('homeCpuBar').style.width = `${cpuPct}%`;
        document.getElementById('homeCpuCores').textContent = `${summary.cpu.logical_cores} cores`;

        // RAM
        const ramPct = summary.memory.used_percent;
        document.getElementById('homeRamVal').textContent = `${ramPct}%`;
        document.getElementById('homeRamBar').style.width = `${ramPct}%`;
        document.getElementById('homeRamTotal').textContent = `${summary.memory.total_gb} GB`;

        // Disk
        const diskPct = summary.disk.used_percent;
        document.getElementById('homeDiskVal').textContent = `${diskPct}%`;
        document.getElementById('homeDiskBar').style.width = `${diskPct}%`;
        document.getElementById('homeDiskFree').textContent = `${summary.disk.free_gb} GB free`;

        // Uptime
        const hrs = Math.floor(summary.uptime_seconds / 3600);
        const mins = Math.floor((summary.uptime_seconds % 3600) / 60);
        document.getElementById('homeUptimeVal').textContent = `Uptime: ${hrs}h ${mins}m`;
        document.getElementById('uptimeMini').textContent = `${hrs}h ${mins}m`;

        document.getElementById('homeRecentActivity').textContent = `System is operating normally on ${summary.os}.`;
    } catch (err) {
        document.getElementById('backendStatusDot').className = 'status-dot offline';
        document.getElementById('backendStatusText').textContent = 'Offline';
    }
}

// ── AI Assistant Chat ──────────────────────────────────────────────────

async function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const question = input.value.trim();
    if (!question) return;

    input.value = '';
    const history = document.getElementById('chatHistory');

    // Add user message
    const userDiv = document.createElement('div');
    userDiv.className = 'chat-msg user';
    userDiv.textContent = question;
    history.appendChild(userDiv);

    // Add AI loading placeholder
    const aiDiv = document.createElement('div');
    aiDiv.className = 'chat-msg ai';
    aiDiv.textContent = 'Thinking and inspecting system...';
    history.appendChild(aiDiv);
    history.scrollTop = history.scrollHeight;

    try {
        const resp = await api('/api/v1/assistant/ask', {
            method: 'POST',
            body: { question, mode: explanationMode },
        });

        aiDiv.innerHTML = '';
        const answerText = document.createElement('div');
        answerText.style.marginBottom = '8px';
        answerText.textContent = resp.answer;
        aiDiv.appendChild(answerText);

        // Render plan approval if present
        if (resp.plan && resp.plan.proposed_action) {
            const plan = resp.plan;
            const action = plan.proposed_action;
            const planCard = document.createElement('div');
            planCard.className = 'chat-section-block';
            planCard.innerHTML = `
                <div class="chat-section-label">Proposed Action (${action.risk_level.toUpperCase()})</div>
                <div style="font-weight: 600; margin: 4px 0;">${action.description}</div>
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">Requires explicit approval before running.</div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-success btn-sm btn-approve-plan" data-plan="${plan.plan_id}" data-action="${action.action_id}">Approve & Run</button>
                    <button class="btn btn-danger btn-sm btn-reject-plan" data-plan="${plan.plan_id}" data-action="${action.action_id}">Reject</button>
                </div>
                <div class="plan-output-box" style="margin-top: 8px; font-size: 12px; display: none;"></div>
            `;
            aiDiv.appendChild(planCard);
        }

        history.scrollTop = history.scrollHeight;
    } catch (err) {
        aiDiv.textContent = `Error: ${err.message}`;
    }
}

// ── File Copilot Tools ────────────────────────────────────────────────

async function loadFileRoots() {
    try {
        const data = await api('/api/v1/files/roots');
        const container = document.getElementById('fileRootsList');
        container.innerHTML = '';
        data.roots.forEach(root => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-secondary btn-sm';
            btn.style.textAlign = 'left';
            btn.textContent = `📁 ${root.name}`;
            btn.onclick = () => {
                document.getElementById('fileCurrentPathInput').value = root.path;
                exploreDirectory(root.path);
            };
            container.appendChild(btn);
        });

        if (data.roots.length > 0 && !document.getElementById('fileCurrentPathInput').value) {
            document.getElementById('fileCurrentPathInput').value = data.roots[0].path;
            exploreDirectory(data.roots[0].path);
        }
    } catch (err) {
        console.error('Error loading roots:', err);
    }
}

async function exploreDirectory(path) {
    const tbody = document.getElementById('fileExplorerTableBody');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align: center;">Loading folder contents...</td></tr>';
    document.getElementById('fileExplorerTitle').textContent = `Contents of ${path}`;

    try {
        const data = await api(`/api/v1/files/list?path=${encodeURIComponent(path)}`);
        tbody.innerHTML = '';
        if (data.items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Folder is empty.</td></tr>';
            return;
        }

        data.items.forEach(item => {
            const tr = document.createElement('tr');
            const icon = item.is_dir ? '📁' : '📄';
            const sizeStr = item.size_bytes !== null ? `${(item.size_bytes / 1024).toFixed(1)} KB` : '--';
            tr.innerHTML = `
                <td>${icon} <span style="font-weight: 500;">${item.name}</span></td>
                <td>${item.is_dir ? 'Directory' : 'File'}</td>
                <td>${sizeStr}</td>
                <td>
                    ${!item.is_dir ? `<button class="btn btn-secondary btn-sm btn-open-file" data-name="${item.name}">Open</button>` : `<button class="btn btn-secondary btn-sm btn-enter-dir" data-name="${item.name}">Explore</button>`}
                    <button class="btn btn-danger btn-sm btn-trash-file" data-name="${item.name}">Trash</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--danger);">${err.message}</td></tr>`;
    }
}

async function openFileInEditor(filePath) {
    try {
        const data = await api(`/api/v1/files/read?path=${encodeURIComponent(filePath)}`);
        currentEditingPath = filePath;
        document.getElementById('fileEditorCard').style.display = 'block';
        document.getElementById('fileEditorName').textContent = data.name;
        document.getElementById('fileEditorContent').value = data.content;
    } catch (err) {
        alert(`Failed to read file: ${err.message}`);
    }
}

async function saveFileEditor() {
    if (!currentEditingPath) return;
    const content = document.getElementById('fileEditorContent').value;
    try {
        const res = await api('/api/v1/files/edit', {
            method: 'POST',
            body: { path: currentEditingPath, new_content: content, create_backup: true },
        });
        alert(`File saved! ${res.backup_path ? 'Backup created.' : ''}`);
    } catch (err) {
        alert(`Error saving file: ${err.message}`);
    }
}

// ── System Monitor ────────────────────────────────────────────────────

async function loadMonitorData() {
    try {
        const data = await api('/api/v1/system/monitor');
        document.getElementById('monMemBreakdown').innerHTML = `
            <strong>Total:</strong> ${data.memory.total_gb} GB |
            <strong>Used:</strong> ${data.memory.used_gb} GB (${data.memory.used_percent}%) |
            <strong>Available:</strong> ${data.memory.available_gb} GB
        `;
        document.getElementById('monSwapBreakdown').innerHTML = `
            <strong>Total:</strong> ${data.swap.total_gb} GB |
            <strong>Used:</strong> ${data.swap.used_gb} GB (${data.swap.used_percent}%)
        `;
        document.getElementById('monTempBreakdown').textContent =
            data.temperatures.available && data.temperatures.readings.length > 0
                ? data.temperatures.readings.map(t => `${t.label}: ${t.temperature_c}°C`).join(', ')
                : 'No hardware temperature sensors detected.';

        document.getElementById('monBatteryBreakdown').textContent =
            data.battery.available
                ? `${data.battery.percent}% (${data.battery.power_plugged ? 'Plugged in' : 'On battery'})`
                : 'Desktop system (No battery sensor).';

        // Per core CPU
        const coresGrid = document.getElementById('monCoresGrid');
        coresGrid.innerHTML = '';
        data.cpu.per_core_percent.forEach((val, idx) => {
            const div = document.createElement('div');
            div.className = 'card';
            div.style.padding = '8px 12px';
            div.innerHTML = `
                <div style="font-size: 11px; color: var(--text-muted);">Core ${idx + 1}</div>
                <div style="font-size: 16px; font-weight: 700;">${val}%</div>
            `;
            coresGrid.appendChild(div);
        });

        // Processes table
        const procBody = document.getElementById('procTableBody');
        procBody.innerHTML = '';
        data.processes.slice(0, 15).forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${p.pid}</td>
                <td><strong>${p.name}</strong></td>
                <td>${p.cpu_percent}%</td>
                <td>${p.memory_percent}%</td>
            `;
            procBody.appendChild(tr);
        });
    } catch (err) {
        console.error('Monitor data error:', err);
    }
}

// ── Developer Tools ────────────────────────────────────────────────────

async function explainPythonError() {
    const errorText = document.getElementById('devErrorInput').value.trim();
    if (!errorText) return;

    const resBox = document.getElementById('devErrorResult');
    resBox.style.display = 'block';
    resBox.innerHTML = 'Analyzing error and generating fix...';

    try {
        const resp = await api('/api/v1/dev/explain-error', {
            method: 'POST',
            body: { error_text: errorText, mode: explanationMode },
        });

        resBox.innerHTML = `
            <div style="background: var(--bg-tertiary); padding: 12px; border-radius: 6px; border-left: 3px solid var(--accent);">
                <div style="font-weight: 700; color: #38bdf8; font-size: 14px;">${resp.error_type}</div>
                <div style="margin: 6px 0;"><strong>Summary:</strong> ${resp.summary}</div>
                <div style="margin: 6px 0;"><strong>Evidence:</strong> <code>${resp.current_evidence}</code></div>
                <div style="margin: 6px 0;"><strong>Fix:</strong> ${resp.recommended_fix}</div>
                ${resp.code_example ? `<div class="code-preview" style="margin-top: 8px;">${resp.code_example}</div>` : ''}
            </div>
        `;
    } catch (err) {
        resBox.textContent = `Error: ${err.message}`;
    }
}

// ── Project Builder ────────────────────────────────────────────────────

async function generateProjectPlan() {
    const template = document.getElementById('builderTemplateSelect').value;
    const name = document.getElementById('builderProjectName').value.trim();
    const dest = document.getElementById('builderDestination').value.trim() || 'Projects';

    if (!name) {
        alert('Please specify a project name.');
        return;
    }

    const previewCard = document.getElementById('builderPreviewCard');
    previewCard.style.display = 'block';
    const treeBox = document.getElementById('builderFileTree');
    treeBox.innerHTML = 'Planning project structure and checking for filename conflicts...';

    try {
        const reqStr = `Create a ${template.replace('_', ' ')} project named ${name} in ${dest}. Include all starter files.`;
        const task = await api('/api/v1/files/task/create', {
            method: 'POST',
            body: { request: reqStr, context_directory: dest },
        });

        currentBuilderTask = task;
        if (task.conflict_detected) {
            treeBox.innerHTML = `<div style="color: var(--danger);">⚠️ Conflict: ${task.conflict_message}</div>`;
            document.getElementById('btnBuilderApproveExecute').style.display = 'none';
            return;
        }

        document.getElementById('btnBuilderApproveExecute').style.display = 'inline-flex';
        treeBox.innerHTML = `
            <div style="font-weight: 600; margin-bottom: 8px;">📁 ${task.target_path}</div>
            <ul style="list-style: none; padding-left: 14px;">
                ${task.planned_files.map(f => `<li>📄 <strong>${f.relative_path}</strong> (${f.size_bytes} bytes) - <span style="color: var(--text-muted);">${f.description}</span></li>`).join('')}
            </ul>
        `;
    } catch (err) {
        treeBox.innerHTML = `<div style="color: var(--danger);">${err.message}</div>`;
    }
}

async function approveAndCreateProject() {
    if (!currentBuilderTask) return;
    const resBox = document.getElementById('builderResultBox');
    resBox.textContent = '1/2 Approving project...';

    try {
        await api(`/api/v1/files/task/${currentBuilderTask.task_id}/approve`, {
            method: 'POST',
            body: { approved: true, approval_token: currentBuilderTask.approval_token },
        });

        resBox.textContent = '2/2 Creating files and verifying on disk...';
        const execRes = await api(`/api/v1/files/task/${currentBuilderTask.task_id}/execute`, {
            method: 'POST',
            body: { approved: true, approval_token: currentBuilderTask.approval_token },
        });

        resBox.innerHTML = `
            <div style="color: var(--success); margin-top: 10px;">
                ✓ ${execRes.task.verification_result}
            </div>
            <button class="btn btn-primary btn-sm" style="margin-top: 8px;" id="btnOpenNewProjectVSCode">Open in VS Code</button>
        `;
        document.getElementById('btnOpenNewProjectVSCode').onclick = () => {
            api('/api/v1/dev/open-editor', {
                method: 'POST',
                body: { target_path: currentBuilderTask.resolved_target_path, editor: 'code' },
            });
        };
    } catch (err) {
        resBox.innerHTML = `<div style="color: var(--danger);">Execution failed: ${err.message}</div>`;
    }
}

// ── Automation Workflows ──────────────────────────────────────────────

async function loadAutomationWorkflows() {
    try {
        const data = await api('/api/v1/automation/workflows');
        const container = document.getElementById('automationWorkflowCards');
        container.innerHTML = '';
        data.workflows.forEach(wf => {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `
                <div class="card-title">${wf.name}</div>
                <div style="font-size: 12.5px; color: var(--text-secondary); margin-bottom: 12px;">${wf.description}</div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span class="badge-pill ${wf.requires_approval ? 'warning' : 'safe'}">${wf.requires_approval ? 'Requires Approval' : 'Automatic'}</span>
                    <button class="btn btn-primary btn-sm btn-run-workflow" data-id="${wf.id}">Run Workflow</button>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        console.error('Error loading workflows:', err);
    }
}

// ── Task History ───────────────────────────────────────────────────────

async function loadTaskHistory() {
    try {
        const data = await api('/api/v1/tasks');
        const tbody = document.getElementById('historyTableBody');
        tbody.innerHTML = '';
        if (data.tasks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No task history.</td></tr>';
            return;
        }

        data.tasks.forEach(t => {
            const tr = document.createElement('tr');
            const statusClass = t.status === 'completed' || t.status === 'verified' ? 'safe' : (t.status === 'failed' ? 'danger' : 'warning');
            tr.innerHTML = `
                <td><span class="badge-pill info">${t.category}</span></td>
                <td><strong>${t.title}</strong></td>
                <td><span class="badge-pill ${statusClass}">${t.status}</span></td>
                <td>${new Date(t.updated_at).toLocaleTimeString()}</td>
                <td style="font-size: 12px; color: var(--text-secondary);">${t.summary || t.request_text}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading history:', err);
    }
}

// ── Notifications ──────────────────────────────────────────────────────

async function loadNotifications() {
    try {
        const data = await api('/api/v1/notifications');
        const container = document.getElementById('notificationsContainer');
        container.innerHTML = '';
        const badge = document.getElementById('navNotifBadge');

        const unread = data.notifications.filter(n => !n.is_read);
        if (unread.length > 0) {
            badge.style.display = 'inline-block';
            badge.textContent = unread.length;
        } else {
            badge.style.display = 'none';
        }

        if (data.notifications.length === 0) {
            container.innerHTML = '<div class="card" style="text-align: center; color: var(--text-muted);">No notifications.</div>';
            return;
        }

        data.notifications.forEach(n => {
            const card = document.createElement('div');
            card.className = 'card';
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="color: ${n.severity === 'warning' ? 'var(--warning)' : (n.severity === 'error' ? 'var(--danger)' : 'var(--text-primary)')};">${n.title}</strong>
                    <span style="font-size: 11px; color: var(--text-muted);">${new Date(n.timestamp).toLocaleTimeString()}</span>
                </div>
                <div style="font-size: 13px; color: var(--text-secondary); margin-top: 6px;">${n.message}</div>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        console.error('Error loading notifications:', err);
    }
}

// ── Security & Audit ───────────────────────────────────────────────────

async function loadSecurityAudit() {
    try {
        const data = await api('/api/v1/assistant/audit');
        const tbody = document.getElementById('auditTableBody');
        tbody.innerHTML = '';
        if (data.entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Audit log is clean.</td></tr>';
            return;
        }

        data.entries.slice(-25).reverse().forEach(e => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-family: var(--font-mono); font-size: 11px;">${new Date(e.timestamp).toLocaleTimeString()}</td>
                <td><strong>${e.event}</strong></td>
                <td style="font-family: var(--font-mono);">${e.plan_id ? e.plan_id.slice(0, 8) : '--'}</td>
                <td style="color: var(--text-secondary); font-size: 12px;">${e.detail}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error('Error loading audit log:', err);
    }
}

// ── Settings ───────────────────────────────────────────────────────────

async function loadSettings() {
    try {
        const settings = await api('/api/v1/settings');
        document.getElementById('settingModeSelect').value = settings.mode;
        document.getElementById('settingIntervalInput').value = settings.refresh_interval_seconds;

        const gemini = await api('/api/v1/settings/gemini-status');
        document.getElementById('settingGeminiStatus').innerHTML = `
            <strong>Status:</strong> ${gemini.configured ? '✅ Active & Configured' : '⚠️ Offline (Using local rule fallback)'}<br>
            <strong>Model:</strong> ${gemini.model}<br>
            <strong>Key Mask:</strong> ${gemini.key_hint}
        `;
    } catch (err) {
        console.error('Settings load error:', err);
    }
}

// ── Initialization & Event Listeners ──────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Nav Click Handlers
    document.getElementById('navList').addEventListener('click', (e) => {
        const item = e.target.closest('.nav-item');
        if (item) switchView(item.dataset.view);
    });

    // Beginner / Advanced Mode Toggles
    const btnBeg = document.getElementById('btnModeBeginner');
    const btnAdv = document.getElementById('btnModeAdvanced');
    btnBeg.onclick = () => {
        explanationMode = 'beginner';
        btnBeg.classList.add('active');
        btnAdv.classList.remove('active');
    };
    btnAdv.onclick = () => {
        explanationMode = 'advanced';
        btnAdv.classList.add('active');
        btnBeg.classList.remove('active');
    };

    // Chat
    document.getElementById('btnChatSend').onclick = sendChatMessage;
    document.getElementById('chatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendChatMessage();
    });

    // Chat plan approve / reject delegation
    document.getElementById('chatHistory').addEventListener('click', async (e) => {
        if (e.target.classList.contains('btn-approve-plan')) {
            const planId = e.target.dataset.plan;
            const actionId = e.target.dataset.action;
            const box = e.target.closest('.chat-section-block').querySelector('.plan-output-box');
            box.style.display = 'block';
            box.textContent = 'Approving and executing action...';
            try {
                await api('/api/v1/assistant/approve', {
                    method: 'POST',
                    body: { plan_id: planId, action_id: actionId, approved: true },
                });
                const execRes = await api('/api/v1/assistant/execute', {
                    method: 'POST',
                    body: { plan_id: planId, action_id: actionId, approved: true },
                });
                box.innerHTML = `<pre class="code-preview">${execRes.output || 'Execution complete.'}</pre>`;
            } catch (err) {
                box.textContent = `Execution failed: ${err.message}`;
            }
        } else if (e.target.classList.contains('btn-reject-plan')) {
            const planId = e.target.dataset.plan;
            const actionId = e.target.dataset.action;
            const box = e.target.closest('.chat-section-block').querySelector('.plan-output-box');
            box.style.display = 'block';
            box.textContent = 'Action rejected.';
            api('/api/v1/assistant/approve', {
                method: 'POST',
                body: { plan_id: planId, action_id: actionId, approved: false },
            });
        }
    });

    // Quick Actions on Home Tab
    document.querySelectorAll('.action-tile').forEach(tile => {
        tile.onclick = () => {
            const action = tile.dataset.action;
            if (action === 'qa-file' || action === 'qa-folder') {
                switchView('files');
            } else if (action === 'qa-project') {
                switchView('builder');
            } else if (action === 'qa-slowdown' || action === 'qa-failed-services') {
                switchView('diagnostics');
            } else if (action === 'qa-organize') {
                switchView('automation');
            } else if (action === 'qa-vscode') {
                switchView('developer');
            } else {
                switchView('assistant');
            }
        };
    });

    // File Explorer Button handlers
    document.getElementById('btnFileListDir').onclick = () => {
        const p = document.getElementById('fileCurrentPathInput').value.trim();
        if (p) exploreDirectory(p);
    };

    document.getElementById('fileExplorerTableBody').addEventListener('click', (e) => {
        const btnOpen = e.target.closest('.btn-open-file');
        const btnEnter = e.target.closest('.btn-enter-dir');
        const btnTrash = e.target.closest('.btn-trash-file');
        const currentDir = document.getElementById('fileCurrentPathInput').value;

        if (btnOpen) {
            const filePath = `${currentDir}/${btnOpen.dataset.name}`;
            openFileInEditor(filePath);
        } else if (btnEnter) {
            const newDir = `${currentDir}/${btnEnter.dataset.name}`;
            document.getElementById('fileCurrentPathInput').value = newDir;
            exploreDirectory(newDir);
        } else if (btnTrash) {
            const filePath = `${currentDir}/${btnTrash.dataset.name}`;
            if (confirm(`Are you sure you want to move '${btnTrash.dataset.name}' to the desktop Trash? (Recoverable)`)) {
                api('/api/v1/files/trash', {
                    method: 'POST',
                    body: { path: filePath, approved: true },
                }).then(() => exploreDirectory(currentDir)).catch(err => alert(err.message));
            }
        }
    });

    document.getElementById('btnFileEditorSave').onclick = saveFileEditor;
    document.getElementById('btnFileEditorClose').onclick = () => {
        document.getElementById('fileEditorCard').style.display = 'none';
    };

    // Diagnostics Quick Cards
    document.getElementById('diagCardSlowdown').onclick = async () => {
        const card = document.getElementById('diagResultCard');
        const content = document.getElementById('diagResultContent');
        card.style.display = 'block';
        content.textContent = 'Inspecting system performance...';
        try {
            const data = await api('/api/v1/system/diagnostics/slowdown');
            content.innerHTML = `
                <strong>Summary:</strong> ${data.summary}<br><br>
                <strong>CPU Load:</strong> ${data.cpu_percent}% (Load avg 1m: ${data.load_average_1m})<br>
                <strong>RAM Usage:</strong> ${data.memory_percent}% | <strong>Swap:</strong> ${data.swap_percent}%<br><br>
                <strong>Top CPU Processes:</strong>
                <ul>${data.top_cpu_processes.map(p => `<li>${p.name} (PID: ${p.pid}) - ${p.cpu_percent}% CPU</li>`).join('')}</ul>
            `;
        } catch (err) { content.textContent = err.message; }
    };

    document.getElementById('diagCardNetwork').onclick = async () => {
        const card = document.getElementById('diagResultCard');
        const content = document.getElementById('diagResultContent');
        card.style.display = 'block';
        content.textContent = 'Diagnosing network connections...';
        try {
            const data = await api('/api/v1/system/diagnostics/network');
            content.innerHTML = `
                <strong>Network Status:</strong> <span class="badge-pill ${data.status === 'connected' ? 'safe' : 'danger'}">${data.status.toUpperCase()}</span><br><br>
                <strong>Summary:</strong> ${data.summary}<br>
                <strong>Active Interfaces:</strong> ${data.active_interfaces.map(i => `${i.interface} (${i.ip})`).join(', ') || 'None'}
            `;
        } catch (err) { content.textContent = err.message; }
    };

    document.getElementById('diagCardJournal').onclick = async () => {
        const card = document.getElementById('diagResultCard');
        const content = document.getElementById('diagResultContent');
        card.style.display = 'block';
        content.textContent = 'Reading journalctl error logs...';
        try {
            const data = await api('/api/v1/system/diagnostics/journal-errors?line_count=15');
            content.innerHTML = `
                <strong>Recent System Errors:</strong> ${data.error_count} found.<br>
                <div class="code-preview" style="margin-top: 10px;">${data.recent_errors.join('\n') || 'No critical system errors.'}</div>
            `;
        } catch (err) { content.textContent = err.message; }
    };

    // Developer Tools
    document.getElementById('btnDevExplain').onclick = explainPythonError;
    document.getElementById('btnDevCreateVenv').onclick = async () => {
        const dir = document.getElementById('devProjectPath').value.trim();
        const resBox = document.getElementById('devToolResult');
        resBox.textContent = 'Creating virtual environment...';
        try {
            const res = await api('/api/v1/dev/venv/create', { method: 'POST', body: { directory: dir } });
            resBox.innerHTML = `<span style="color: var(--success);">✓ ${res.message}</span>`;
        } catch (err) { resBox.textContent = err.message; }
    };

    document.getElementById('btnDevRunTests').onclick = async () => {
        const dir = document.getElementById('devProjectPath').value.trim();
        const resBox = document.getElementById('devToolResult');
        resBox.textContent = 'Running project unit tests...';
        try {
            const res = await api('/api/v1/dev/tests/run', { method: 'POST', body: { project_directory: dir } });
            resBox.innerHTML = `
                <div style="font-weight: 600; color: ${res.success ? 'var(--success)' : 'var(--danger)'};">${res.summary}</div>
                <div class="code-preview" style="margin-top: 8px;">${res.output || 'No output.'}</div>
            `;
        } catch (err) { resBox.textContent = err.message; }
    };

    document.getElementById('btnDevGitStatus').onclick = async () => {
        const dir = document.getElementById('devProjectPath').value.trim();
        const resBox = document.getElementById('devToolResult');
        resBox.textContent = 'Inspecting Git status...';
        try {
            const res = await api(`/api/v1/dev/git/status?path=${encodeURIComponent(dir)}`);
            if (!res.is_git_repo) {
                resBox.textContent = 'Directory is not a Git repository.';
                return;
            }
            resBox.innerHTML = `
                <strong>Branch:</strong> ${res.branch} | <strong>Status:</strong> ${res.clean ? 'Clean' : 'Modified'}<br>
                ${res.modified_files.length ? `<strong>Modified:</strong> ${res.modified_files.join(', ')}<br>` : ''}
                ${res.recent_commits.length ? `<strong>Recent Commits:</strong><br>${res.recent_commits.map(c => `• ${c}`).join('<br>')}` : ''}
            `;
        } catch (err) { resBox.textContent = err.message; }
    };

    document.getElementById('btnDevOpenVSCode').onclick = async () => {
        const dir = document.getElementById('devProjectPath').value.trim();
        const resBox = document.getElementById('devToolResult');
        try {
            const res = await api('/api/v1/dev/open-editor', { method: 'POST', body: { target_path: dir, editor: 'code' } });
            resBox.innerHTML = `<span style="color: var(--success);">${res.message}</span>`;
        } catch (err) { resBox.textContent = err.message; }
    };

    // Project Builder
    document.getElementById('btnBuilderGeneratePlan').onclick = generateProjectPlan;
    document.getElementById('btnBuilderApproveExecute').onclick = approveAndCreateProject;

    // Automation workflow run delegation
    document.getElementById('automationWorkflowCards').addEventListener('click', async (e) => {
        if (e.target.classList.contains('btn-run-workflow')) {
            const wfId = e.target.dataset.id;
            e.target.textContent = 'Running...';
            try {
                const res = await api(`/api/v1/automation/run/${wfId}`, {
                    method: 'POST',
                    body: { workflow_id: wfId, approved: true },
                });
                alert(`Workflow completed: ${res.status}`);
            } catch (err) {
                alert(`Workflow failed: ${err.message}`);
            } finally {
                e.target.textContent = 'Run Workflow';
            }
        }
    });

    // Global refresh button
    document.getElementById('btnRefreshGlobal').onclick = () => {
        refreshHomeData();
        if (activeView === 'monitor') loadMonitorData();
    };

    // Initial load
    refreshHomeData();
    loadNotifications();

    // Polling timer
    refreshTimer = setInterval(() => {
        refreshHomeData();
        if (activeView === 'monitor') loadMonitorData();
    }, 5000);
});

