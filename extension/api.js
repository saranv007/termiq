import Soup from 'gi://Soup?version=3.0';
import GLib from 'gi://GLib';

const API_BASE = 'http://127.0.0.1:8765';
const session = new Soup.Session();

async function request(path, method = 'GET', body = null) {
    const message = Soup.Message.new(method, `${API_BASE}${path}`);

    if (body !== null) {
        const bytes = new GLib.Bytes(
            new TextEncoder().encode(JSON.stringify(body))
        );

        message.set_request_body_from_bytes('application/json', bytes);
    }

    const responseBytes = await new Promise((resolve, reject) => {
        session.send_and_read_async(
            message,
            GLib.PRIORITY_DEFAULT,
            null,
            (session, result) => {
                try {
                    resolve(session.send_and_read_finish(result));
                } catch (error) {
                    reject(error);
                }
            }
        );
    });

    const text = new TextDecoder().decode(responseBytes.get_data());

    if (message.get_status() < 200 || message.get_status() >= 300) {
        throw new Error(`HTTP ${message.get_status()}: ${text}`);
    }

    return JSON.parse(text);
}

// ── System Copilot API ────────────────────────────────────────────────

export function getSystemSummary() {
    return request('/api/v1/system/summary');
}

export function askTermiq(question) {
    return request('/api/v1/assistant/ask', 'POST', {question});
}

export function approvePlanAction(planId, actionId, approved) {
    return request('/api/v1/assistant/approve', 'POST', {
        plan_id: planId,
        action_id: actionId,
        approved,
    });
}

export function executePlanAction(planId, actionId) {
    return request('/api/v1/assistant/execute', 'POST', {
        plan_id: planId,
        action_id: actionId,
        approved: true,
    });
}

export function verifyPlanAction(planId) {
    return request(`/api/v1/assistant/verify/${planId}`);
}

export function getPlan(planId) {
    return request(`/api/v1/assistant/plan/${planId}`);
}

// ── File & Folder Copilot API (V2.0) ──────────────────────────────────

export function createFileTask(requestText, contextDirectory = null) {
    return request('/api/v1/files/task/create', 'POST', {
        request: requestText,
        context_directory: contextDirectory,
    });
}

export function clarifyFileTask(taskId, answers = {}, text = null) {
    return request(`/api/v1/files/task/${taskId}/clarify`, 'POST', {
        answers,
        text,
    });
}

export function getFileTask(taskId) {
    return request(`/api/v1/files/task/${taskId}`);
}

export function approveFileTask(taskId, approved, approvalToken = null) {
    return request(`/api/v1/files/task/${taskId}/approve`, 'POST', {
        approved,
        approval_token: approvalToken,
    });
}

export function executeFileTask(taskId, approvalToken = null) {
    return request(`/api/v1/files/task/${taskId}/execute`, 'POST', {
        approved: true,
        approval_token: approvalToken,
    });
}

export function getFileRoots() {
    return request('/api/v1/files/roots');
}

export function listDirectory(path, maxItems = 100) {
    const encoded = encodeURIComponent(path);
    return request(`/api/v1/files/list?path=${encoded}&max_items=${maxItems}`);
}

export function searchFiles(path, pattern, maxItems = 100) {
    const encPath = encodeURIComponent(path);
    const encPattern = encodeURIComponent(pattern);
    return request(`/api/v1/files/search?path=${encPath}&pattern=${encPattern}&max_items=${maxItems}`);
}

export function readTextFile(path, maxBytes = 65536) {
    const encoded = encodeURIComponent(path);
    return request(`/api/v1/files/read?path=${encoded}&max_bytes=${maxBytes}`);
}
