import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {
    getSystemSummary,
    askTermiq,
    approvePlanAction,
    executePlanAction,
    verifyPlanAction,
} from './api.js';

function extractAnswer(response) {
    if (typeof response === 'string')
        return response;

    if (response && typeof response === 'object') {
        for (const key of [
            'answer', 'response', 'message',
            'reply', 'result', 'output',
        ]) {
            if (typeof response[key] === 'string')
                return response[key];
        }

        if (response.data)
            return extractAnswer(response.data);

        return JSON.stringify(response, null, 2);
    }

    return String(response);
}

export function createTermiqPanel() {
    const indicator = new PanelMenu.Button(0.0, 'TERMIQ', false);

    const buttonLabel = new St.Label({
        text: 'TERMIQ',
        y_align: Clutter.ActorAlign.CENTER,
    });

    indicator.add_child(buttonLabel);

    function addStatusRow(text) {
        const item = new PopupMenu.PopupBaseMenuItem({
            reactive: false,
            can_focus: false,
        });

        const label = new St.Label({
            text,
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: true,
        });

        item.add_child(label);
        indicator.menu.addMenuItem(item);

        return label;
    }

    // System monitor
    const cpuLabel = addStatusRow('CPU: Loading...');
    const memoryLabel = addStatusRow('RAM: Loading...');
    const diskLabel = addStatusRow('Disk: Loading...');
    const connectionLabel = addStatusRow('Backend: Connecting...');

    // Assistant input
    indicator.menu.addMenuItem(
        new PopupMenu.PopupSeparatorMenuItem()
    );

    addStatusRow('Ask TERMIQ');

    const questionEntry = new St.Entry({
        name: 'termiq-question-entry',
        hint_text: 'Ask about your Linux system...',
        can_focus: true,
        x_expand: true,
    });
    questionEntry.set_width(240);

    const askButton = new St.Button({
        label: 'Ask',
        can_focus: true,
        reactive: true,
        track_hover: true,
        style_class: 'termiq-button',
    });

    const questionRow = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });

    const questionBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
        style: 'spacing: 6px;',
    });

    questionBox.add_child(questionEntry);
    questionBox.add_child(askButton);
    questionRow.add_child(questionBox);
    indicator.menu.addMenuItem(questionRow);

    // Evidence section: create first, then hide.
    const evidenceItem = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });
    evidenceItem.visible = false;

    const evidenceLabel = new St.Label({
        text: '',
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
        style_class: 'termiq-status',
    });

    evidenceLabel.set_style('max-width: 320px;');
    evidenceLabel.get_clutter_text().set_line_wrap(true);
    evidenceItem.add_child(evidenceLabel);
    indicator.menu.addMenuItem(evidenceItem);

    // AI answer
    const answerItem = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });

    const answerLabel = new St.Label({
        text: 'Type a question and press Ask.',
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
    });

    answerLabel.set_style('max-width: 320px;');
    answerLabel.get_clutter_text().set_line_wrap(true);

    answerItem.add_child(answerLabel);
    indicator.menu.addMenuItem(answerItem);

    // Troubleshooting plan: create first, then hide.
    const planItem = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });
    planItem.visible = false;

    const planContainer = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        style_class: 'termiq-plan-box',
    });

    const planTitleLabel = new St.Label({
        text: 'Proposed Action',
        style_class: 'termiq-plan-title',
    });

    const planDescLabel = new St.Label({
        text: '',
        style_class: 'termiq-plan-desc',
    });

    planDescLabel.set_style('max-width: 320px;');
    planDescLabel.get_clutter_text().set_line_wrap(true);

    const planRiskLabel = new St.Label({
        text: '',
        style_class: 'termiq-plan-badge-safe',
    });

    // Explicit approval controls
    const approveButton = new St.Button({
        label: 'Approve & Run',
        style_class: 'termiq-btn-approve',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    const rejectButton = new St.Button({
        label: 'Reject',
        style_class: 'termiq-btn-reject',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    const buttonBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
        style: 'spacing: 8px; margin-top: 6px;',
    });

    buttonBox.add_child(approveButton);
    buttonBox.add_child(rejectButton);

    const executionStatusLabel = new St.Label({
        text: '',
        style_class: 'termiq-status',
        visible: false,
    });

    executionStatusLabel.set_style('max-width: 320px;');
    executionStatusLabel.get_clutter_text().set_line_wrap(true);

    const outputLabel = new St.Label({
        text: '',
        style_class: 'termiq-output-text',
        visible: false,
    });

    outputLabel.set_style('max-width: 320px;');
    outputLabel.get_clutter_text().set_line_wrap(true);

    const verificationLabel = new St.Label({
        text: '',
        style_class: 'termiq-verify-success',
        visible: false,
    });

    verificationLabel.set_style('max-width: 320px;');
    verificationLabel.get_clutter_text().set_line_wrap(true);

    planContainer.add_child(planTitleLabel);
    planContainer.add_child(planDescLabel);
    planContainer.add_child(planRiskLabel);
    planContainer.add_child(buttonBox);
    planContainer.add_child(executionStatusLabel);
    planContainer.add_child(outputLabel);
    planContainer.add_child(verificationLabel);

    planItem.add_child(planContainer);
    indicator.menu.addMenuItem(planItem);

    // State tracking
    let currentPlan = null;
    let isBusy = false;
    let destroyed = false;
    let timerId = null;

    // Refresh live system statistics
    async function refreshStats() {
        if (destroyed)
            return;

        try {
            const data = await getSystemSummary();

            if (destroyed)
                return;

            cpuLabel.set_text(
                `CPU usage: ${Number(data.cpu.usage_percent).toFixed(1)}%`
            );

            memoryLabel.set_text(
                `RAM: ${Number(data.memory.used_percent).toFixed(1)}% used`
            );

            diskLabel.set_text(
                `Disk: ${Number(data.disk.used_percent).toFixed(1)}% used`
            );

            connectionLabel.set_text('Backend: Connected');
        } catch (error) {
            if (!destroyed)
                connectionLabel.set_text('Backend: Offline');

            console.error('TERMIQ system summary error:', error);
        }
    }

    // Submit a question to the assistant
    async function submitQuestion() {
        if (isBusy || destroyed)
            return;

        const question = questionEntry.get_text().trim();

        if (!question) {
            answerLabel.set_text('Please type a question first.');
            return;
        }

        isBusy = true;
        askButton.reactive = false;
        planItem.visible = false;
        evidenceItem.visible = false;
        currentPlan = null;

        answerLabel.set_text(
            'TERMIQ is diagnosing your system and consulting AI...'
        );

        try {
            const response = await askTermiq(question);

            if (destroyed)
                return;

            // Display diagnostic evidence, if provided.
            if (response.findings && response.findings.length > 0) {
                const issues = response.findings
                    .filter(f => f.issue)
                    .map(f => f.issue)
                    .join('; ');

                if (issues) {
                    evidenceLabel.set_text(`Evidence: ${issues}`);
                    evidenceItem.visible = true;
                }
            }

            answerLabel.set_text(extractAnswer(response));

            // Display a proposed action, if the backend returned one.
            if (response.plan && response.plan.proposed_action) {
                const action = response.plan.proposed_action;

                currentPlan = {
                    planId: response.plan.plan_id,
                    actionId: action.action_id,
                    actionType: action.action_type,
                    riskLevel: action.risk_level || 'safe',
                };

                planTitleLabel.set_text(
                    `Proposed Action: ${action.action_type}`
                );

                planDescLabel.set_text(
                    action.description || 'Run system diagnostic'
                );

                const isSafe = action.risk_level === 'safe';

                planRiskLabel.set_text(
                    `Risk: ${action.risk_level || 'safe'} — Explicit approval required`
                );

                planRiskLabel.style_class = isSafe
                    ? 'termiq-plan-badge-safe'
                    : 'termiq-plan-badge-warn';

                buttonBox.visible = true;
                approveButton.reactive = true;
                approveButton.visible = true;
                rejectButton.reactive = true;
                rejectButton.visible = true;

                executionStatusLabel.set_text('');
                executionStatusLabel.visible = false;

                outputLabel.set_text('');
                outputLabel.visible = false;

                verificationLabel.set_text('');
                verificationLabel.visible = false;

                planItem.visible = true;
            }
        } catch (error) {
            if (!destroyed) {
                answerLabel.set_text(`Request failed: ${error.message}`);
                console.error('TERMIQ assistant error:', error);
            }
        } finally {
            isBusy = false;

            if (!destroyed)
                askButton.reactive = true;
        }
    }

    // Approve and run a proposed, backend-validated action.
    async function handleApprove() {
        if (!currentPlan || isBusy || destroyed)
            return;

        isBusy = true;
        approveButton.reactive = false;
        rejectButton.reactive = false;

        executionStatusLabel.set_text(
            '1/3 Submitting user approval...'
        );
        executionStatusLabel.visible = true;

        try {
            const approveResult = await approvePlanAction(
                currentPlan.planId,
                currentPlan.actionId,
                true
            );

            if (destroyed)
                return;

            if (!approveResult.success) {
                executionStatusLabel.set_text(
                    `Approval rejected: ${approveResult.message || 'Not approved'}`
                );
                return;
            }

            executionStatusLabel.set_text(
                '2/3 Executing approved diagnostic...'
            );

            const execResult = await executePlanAction(
                currentPlan.planId,
                currentPlan.actionId
            );

            if (destroyed)
                return;

            if (!execResult.success) {
                executionStatusLabel.set_text(
                    `Execution failed: ${execResult.error || 'Unknown error'}`
                );
                return;
            }

            // Show a small output preview.
            if (execResult.stdout) {
                const preview = execResult.stdout
                    .trim()
                    .split('\n')
                    .slice(0, 6)
                    .join('\n');

                outputLabel.set_text(preview || '(Empty output)');
                outputLabel.visible = true;
            } else if (execResult.stderr) {
                outputLabel.set_text(
                    `stderr: ${execResult.stderr.trim().slice(0, 200)}`
                );
                outputLabel.visible = true;
            }

            executionStatusLabel.set_text(
                '3/3 Verifying execution result...'
            );

            const verifyResult = await verifyPlanAction(
                currentPlan.planId
            );

            if (destroyed)
                return;

            if (verifyResult.verified) {
                verificationLabel.set_text(
                    `Result Verified: ${verifyResult.detail}`
                );
                verificationLabel.style_class = 'termiq-verify-success';

                executionStatusLabel.set_text(
                    'Status: Executed and verified'
                );
            } else {
                verificationLabel.set_text(
                    `Verification notice: ${verifyResult.detail}`
                );
                verificationLabel.style_class = 'termiq-verify-fail';

                executionStatusLabel.set_text(
                    'Status: Completed with verification notice'
                );
            }

            verificationLabel.visible = true;
            buttonBox.visible = false;
        } catch (error) {
            if (!destroyed) {
                executionStatusLabel.set_text(
                    `Error: ${error.message}`
                );
                console.error('TERMIQ execution error:', error);
            }
        } finally {
            isBusy = false;
        }
    }

    // Reject the proposed action without executing it.
    async function handleReject() {
        if (!currentPlan || isBusy || destroyed)
            return;

        isBusy = true;
        approveButton.reactive = false;
        rejectButton.reactive = false;

        try {
            await approvePlanAction(
                currentPlan.planId,
                currentPlan.actionId,
                false
            );

            if (destroyed)
                return;

            executionStatusLabel.set_text('Action rejected by user.');
            executionStatusLabel.visible = true;
            buttonBox.visible = false;
        } catch (error) {
            if (!destroyed) {
                executionStatusLabel.set_text(
                    `Rejection failed: ${error.message}`
                );
                executionStatusLabel.visible = true;

                console.error('TERMIQ rejection error:', error);
            }
        } finally {
            isBusy = false;
        }
    }

    // UI signal handlers
    askButton.connect('clicked', () => {
        submitQuestion();
    });

    questionEntry.get_clutter_text().connect('activate', () => {
        submitQuestion();
    });

    approveButton.connect('clicked', () => {
        handleApprove();
    });

    rejectButton.connect('clicked', () => {
        handleReject();
    });

    indicator.menu.connect('open-state-changed', (_menu, isOpen) => {
        if (isOpen && !destroyed) {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                if (!destroyed)
                    global.stage.set_key_focus(questionEntry);

                return GLib.SOURCE_REMOVE;
            });
        }
    });

    indicator.menu.addMenuItem(
        new PopupMenu.PopupSeparatorMenuItem()
    );

    indicator.menu.addAction(
        'Refresh system stats',
        () => refreshStats()
    );

    // Initial metrics request.
    refreshStats();

    // Refresh metrics every five seconds.
    timerId = GLib.timeout_add_seconds(
        GLib.PRIORITY_DEFAULT,
        5,
        () => {
            if (destroyed)
                return GLib.SOURCE_REMOVE;

            refreshStats();
            return GLib.SOURCE_CONTINUE;
        }
    );

    // Clean up when GNOME destroys the extension panel.
    indicator.connect('destroy', () => {
        destroyed = true;

        if (timerId !== null) {
            GLib.source_remove(timerId);
            timerId = null;
        }
    });

    return indicator;
}
