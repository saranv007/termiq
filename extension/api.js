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
