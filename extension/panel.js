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
    createFileTask,
    clarifyFileTask,
    approveFileTask,
    executeFileTask,
    openWorkspace,
    getNotifications,
    openInEditor,
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

    // ── Open Full Workspace Prominent Button ───────────────────────
    const wsRow = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });

    const openWorkspaceBtn = new St.Button({
        label: '🚀 Open TERMIQ Workspace',
        style_class: 'termiq-btn-workspace',
        can_focus: true,
        reactive: true,
        track_hover: true,
        x_expand: true,
    });

    wsRow.add_child(openWorkspaceBtn);
    indicator.menu.addMenuItem(wsRow);

    // ── System Monitor Section ─────────────────────────────────────
    const cpuLabel = addStatusRow('CPU: Loading...');
    const memoryLabel = addStatusRow('RAM: Loading...');
    const diskLabel = addStatusRow('Disk: Loading...');
    const connectionLabel = addStatusRow('Backend: Connecting...');

    // Notification alert row (hidden initially)
    const notifItem = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });
    notifItem.visible = false;
    const notifLabel = new St.Label({
        text: '',
        style_class: 'termiq-notif-alert',
        x_expand: true,
    });
    notifItem.add_child(notifLabel);
    indicator.menu.addMenuItem(notifItem);

    indicator.menu.addMenuItem(
        new PopupMenu.PopupSeparatorMenuItem()
    );

    // ── Quick Action Shortcuts Bar ─────────────────────────────────
    const qaTitleRow = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });
    const qaTitleLabel = new St.Label({
        text: 'Quick Actions',
        style_class: 'termiq-status',
        style: 'font-weight: bold;',
    });
    qaTitleRow.add_child(qaTitleLabel);
    indicator.menu.addMenuItem(qaTitleRow);

    const qaRow1 = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
    const qaBox1 = new St.BoxLayout({ vertical: false, x_expand: true, style_class: 'termiq-quick-actions-box' });

    const btnQaSlowdown = new St.Button({ label: '🐌 Slowdown', style_class: 'termiq-qa-chip', can_focus: true, reactive: true });
    const btnQaRam = new St.Button({ label: '🧠 RAM Usage', style_class: 'termiq-qa-chip', can_focus: true, reactive: true });
    const btnQaServices = new St.Button({ label: '⚙️ Services', style_class: 'termiq-qa-chip', can_focus: true, reactive: true });

    qaBox1.add_child(btnQaSlowdown);
    qaBox1.add_child(btnQaRam);
    qaBox1.add_child(btnQaServices);
    qaRow1.add_child(qaBox1);
    indicator.menu.addMenuItem(qaRow1);

    const qaRow2 = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
    const qaBox2 = new St.BoxLayout({ vertical: false, x_expand: true, style_class: 'termiq-quick-actions-box' });

    const btnQaCalc = new St.Button({ label: '🏗️ Calculator', style_class: 'termiq-qa-chip', can_focus: true, reactive: true });
    const btnQaOrganize = new St.Button({ label: '📦 Organize DL', style_class: 'termiq-qa-chip', can_focus: true, reactive: true });
    const btnQaVsCode = new St.Button({ label: '💻 VS Code', style_class: 'termiq-qa-chip', can_focus: true, reactive: true });

    qaBox2.add_child(btnQaCalc);
    qaBox2.add_child(btnQaOrganize);
    qaBox2.add_child(btnQaVsCode);
    qaRow2.add_child(qaBox2);
    indicator.menu.addMenuItem(qaRow2);

    indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

    // ── Mode Switcher Row ──────────────────────────────────────────
    const modeRow = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });

    const modeBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
        style_class: 'termiq-mode-bar',
    });

    const sysModeBtn = new St.Button({
        label: 'System Assistant',
        style_class: 'termiq-mode-btn-active',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    const fileModeBtn = new St.Button({
        label: 'File Copilot',
        style_class: 'termiq-mode-btn',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    modeBox.add_child(sysModeBtn);
    modeBox.add_child(fileModeBtn);
    modeRow.add_child(modeBox);
    indicator.menu.addMenuItem(modeRow);

    // ══════════════════════════════════════════════════════════════
    // SYSTEM COPILOT SECTION
    // ══════════════════════════════════════════════════════════════

    const sysHeaderLabel = addStatusRow('Ask System Assistant');

    const questionEntry = new St.Entry({
        name: 'termiq-question-entry',
        hint_text: 'Ask about CPU, RAM, services...',
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

    // Diagnostic Evidence item
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

    // AI Answer item
    const answerItem = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });

    const answerLabel = new St.Label({
        text: 'Type a question or pick a quick action above.',
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
    });
    answerLabel.set_style('max-width: 320px;');
    answerLabel.get_clutter_text().set_line_wrap(true);
    answerItem.add_child(answerLabel);
    indicator.menu.addMenuItem(answerItem);

    // System Diagnostic Plan item
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

    // ══════════════════════════════════════════════════════════════
    // FILE & FOLDER COPILOT SECTION (V2.0 & V2.1)
    // ══════════════════════════════════════════════════════════════

    const fileSectionItem = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });
    fileSectionItem.visible = false;

    const fileContainer = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        style: 'spacing: 8px;',
    });

    const fileHeaderLabel = new St.Label({
        text: 'File & Folder Copilot',
        style_class: 'termiq-title',
        style: 'font-size: 14px;',
    });

    // Request Input Row
    const fileInputBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
        style: 'spacing: 6px;',
    });

    const fileRequestEntry = new St.Entry({
        name: 'termiq-file-entry',
        hint_text: 'e.g., Create calculator in Projects...',
        can_focus: true,
        x_expand: true,
    });
    fileRequestEntry.set_width(240);

    const filePlanButton = new St.Button({
        label: 'Plan',
        can_focus: true,
        reactive: true,
        track_hover: true,
        style_class: 'termiq-button',
    });

    fileInputBox.add_child(fileRequestEntry);
    fileInputBox.add_child(filePlanButton);

    // Clarification Container
    const fileClarifyContainer = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        style_class: 'termiq-clarify-box',
        visible: false,
    });

    const fileClarifyQuestionLabel = new St.Label({
        text: '',
        style_class: 'termiq-clarify-text',
    });
    fileClarifyQuestionLabel.set_style('max-width: 320px;');
    fileClarifyQuestionLabel.get_clutter_text().set_line_wrap(true);

    const fileClarifyAnswerEntry = new St.Entry({
        hint_text: 'Type your answer here...',
        can_focus: true,
        x_expand: true,
    });

    const fileClarifySubmitBtn = new St.Button({
        label: 'Submit Details',
        style_class: 'termiq-btn-approve',
        can_focus: true,
        reactive: true,
        track_hover: true,
        style: 'margin-top: 4px;',
    });

    fileClarifyContainer.add_child(fileClarifyQuestionLabel);
    fileClarifyContainer.add_child(fileClarifyAnswerEntry);
    fileClarifyContainer.add_child(fileClarifySubmitBtn);

    // Conflict & Path Container
    const fileTargetDetailsBox = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        style: 'spacing: 4px; margin-top: 4px;',
        visible: false,
    });

    const fileConflictBanner = new St.Label({
        text: '',
        style_class: 'termiq-conflict-text',
        visible: false,
    });
    fileConflictBanner.set_style('max-width: 320px;');
    fileConflictBanner.get_clutter_text().set_line_wrap(true);

    const filePathBadge = new St.Label({
        text: '',
        style_class: 'termiq-path-badge',
    });
    filePathBadge.set_style('max-width: 320px;');
    filePathBadge.get_clutter_text().set_line_wrap(true);

    const fileSummaryLabel = new St.Label({
        text: '',
        style_class: 'termiq-status',
    });
    fileSummaryLabel.set_style('max-width: 320px;');
    fileSummaryLabel.get_clutter_text().set_line_wrap(true);

    fileTargetDetailsBox.add_child(fileConflictBanner);
    fileTargetDetailsBox.add_child(filePathBadge);
    fileTargetDetailsBox.add_child(fileSummaryLabel);

    // File Preview Box
    const filePreviewBox = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        style: 'spacing: 4px;',
        visible: false,
    });

    const filePreviewHeaderLabel = new St.Label({
        text: 'File Preview (SHA-256 Protected)',
        style_class: 'termiq-plan-title',
        style: 'font-size: 11px;',
    });

    const filePreviewContentLabel = new St.Label({
        text: '',
        style_class: 'termiq-file-preview',
    });
    filePreviewContentLabel.set_style('max-width: 320px;');
    filePreviewContentLabel.get_clutter_text().set_line_wrap(true);

    filePreviewBox.add_child(filePreviewHeaderLabel);
    filePreviewBox.add_child(filePreviewContentLabel);

    // Approval & Execution Actions
    const fileActionBtnBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
        style: 'spacing: 8px; margin-top: 6px;',
        visible: false,
    });

    const fileApproveBtn = new St.Button({
        label: 'Approve & Create',
        style_class: 'termiq-btn-approve',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    const fileCancelBtn = new St.Button({
        label: 'Cancel',
        style_class: 'termiq-btn-reject',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    fileActionBtnBox.add_child(fileApproveBtn);
    fileActionBtnBox.add_child(fileCancelBtn);

    // Verification & Results
    const fileExecutionProgressLabel = new St.Label({
        text: '',
        style_class: 'termiq-status',
        visible: false,
    });
    fileExecutionProgressLabel.set_style('max-width: 320px;');
    fileExecutionProgressLabel.get_clutter_text().set_line_wrap(true);

    const fileVerificationBanner = new St.Label({
        text: '',
        style_class: 'termiq-verify-success',
        visible: false,
    });
    fileVerificationBanner.set_style('max-width: 320px;');
    fileVerificationBanner.get_clutter_text().set_line_wrap(true);

    fileContainer.add_child(fileHeaderLabel);
    fileContainer.add_child(fileInputBox);
    fileContainer.add_child(fileClarifyContainer);
    fileContainer.add_child(fileTargetDetailsBox);
    fileContainer.add_child(filePreviewBox);
    fileContainer.add_child(fileActionBtnBox);
    fileContainer.add_child(fileExecutionProgressLabel);
    fileContainer.add_child(fileVerificationBanner);

    fileSectionItem.add_child(fileContainer);
    indicator.menu.addMenuItem(fileSectionItem);

    // ── Recent Task Row ────────────────────────────────────────────
    const recentTaskRow = addStatusRow('Recent: Ready for requests');

    // ── State Variables ────────────────────────────────────────────
    let currentPlan = null;
    let currentFileTask = null;
    let timerId = null;
    let isBusy = false;
    let destroyed = false;
    let activeMode = 'system'; // 'system' | 'file'

    // ── Mode Switch Logic ──────────────────────────────────────────
    function setMode(mode) {
        activeMode = mode;
        if (mode === 'file') {
            sysModeBtn.style_class = 'termiq-mode-btn';
            fileModeBtn.style_class = 'termiq-mode-btn-active';
            sysHeaderLabel.visible = false;
            questionRow.visible = false;
            evidenceItem.visible = false;
            answerItem.visible = false;
            planItem.visible = false;
            fileSectionItem.visible = true;
        } else {
            sysModeBtn.style_class = 'termiq-mode-btn-active';
            fileModeBtn.style_class = 'termiq-mode-btn';
            sysHeaderLabel.visible = true;
            questionRow.visible = true;
            answerItem.visible = true;
            if (currentPlan)
                planItem.visible = true;
            fileSectionItem.visible = false;
        }
    }

    sysModeBtn.connect('clicked', () => setMode('system'));
    fileModeBtn.connect('clicked', () => setMode('file'));

    // Open Workspace Action
    openWorkspaceBtn.connect('clicked', () => {
        indicator.menu.close();
        openWorkspace();
    });

    // Quick Action Click Handlers
    btnQaSlowdown.connect('clicked', () => {
        setMode('system');
        questionEntry.set_text('Why is my laptop running slowly?');
        submitQuestion();
    });

    btnQaRam.connect('clicked', () => {
        setMode('system');
        questionEntry.set_text('Which applications are consuming RAM?');
        submitQuestion();
    });

    btnQaServices.connect('clicked', () => {
        setMode('system');
        questionEntry.set_text('Show me which services have failed');
        submitQuestion();
    });

    btnQaCalc.connect('clicked', () => {
        setMode('file');
        fileRequestEntry.set_text('Create a Python calculator project in my Projects folder');
        handleFilePlan();
    });

    btnQaOrganize.connect('clicked', () => {
        setMode('file');
        fileRequestEntry.set_text('Organize my Downloads folder by file type');
        handleFilePlan();
    });

    btnQaVsCode.connect('clicked', () => {
        openInEditor('Projects').then(res => {
            recentTaskRow.set_text(`VS Code: ${res.message}`);
        }).catch(err => {
            recentTaskRow.set_text(`VS Code error: ${err.message}`);
        });
    });

    // ── System Stats Refresh ───────────────────────────────────────
    async function refreshStats() {
        if (destroyed)
            return;

        try {
            const summary = await getSystemSummary();
            if (destroyed)
                return;

            cpuLabel.set_text(
                `CPU: ${summary.cpu.usage_percent}% ` +
                `(${summary.cpu.logical_cores} cores)`
            );
            memoryLabel.set_text(
                `RAM: ${summary.memory.used_percent}% ` +
                `(${summary.memory.available_gb} GB free)`
            );
            diskLabel.set_text(
                `Disk: ${summary.disk.used_percent}% ` +
                `(${summary.disk.free_gb} GB free)`
            );
            connectionLabel.set_text('Backend: Connected');

            // Check notifications periodically
            getNotifications().then(notifData => {
                if (destroyed) return;
                const items = notifData.notifications || [];
                if (items.length > 0) {
                    notifItem.visible = true;
                    notifLabel.set_text(`⚠️ Alert: ${items[0].title} — ${items[0].message}`);
                } else {
                    notifItem.visible = false;
                }
            }).catch(() => {});

        } catch (error) {
            if (destroyed)
                return;
            cpuLabel.set_text('CPU: Unavailable');
            memoryLabel.set_text('RAM: Unavailable');
            diskLabel.set_text('Disk: Unavailable');
            connectionLabel.set_text('Backend: Disconnected');
        }
    }

    // ── Question Submission ────────────────────────────────────────
    async function submitQuestion() {
        if (isBusy || destroyed)
            return;

        const question = questionEntry.get_text().trim();
        if (!question)
            return;

        isBusy = true;
        askButton.reactive = false;
        questionEntry.reactive = false;
        answerLabel.set_text('Thinking and analyzing system...');
        evidenceItem.visible = false;
        planItem.visible = false;
        currentPlan = null;

        try {
            const response = await askTermiq(question);
            if (destroyed)
                return;

            const text = extractAnswer(response);
            answerLabel.set_text(text);
            recentTaskRow.set_text(`Recent: ${question.slice(0, 30)}...`);

            if (response.findings && response.findings.length > 0) {
                const issues = response.findings
                    .map(f => f.issue || f.severity || '')
                    .filter(Boolean)
                    .join('; ');
                if (issues) {
                    evidenceLabel.set_text(`Evidence: ${issues}`);
                    evidenceItem.visible = true;
                }
            }

            if (response.plan && response.plan.proposed_action) {
                currentPlan = response.plan;
                const action = currentPlan.proposed_action;
                planDescLabel.set_text(action.description);
                planRiskLabel.set_text(
                    `Risk: ${action.risk_level.toUpperCase()} (Approval Required)`
                );
                executionStatusLabel.visible = false;
                outputLabel.visible = false;
                verificationLabel.visible = false;
                approveButton.reactive = true;
                rejectButton.reactive = true;
                planItem.visible = true;
            }
        } catch (error) {
            if (!destroyed)
                answerLabel.set_text(`Error: ${error.message}`);
        } finally {
            isBusy = false;
            askButton.reactive = true;
            questionEntry.reactive = true;
        }
    }

    // ── System Diagnostic Action Approve/Reject ───────────────────
    async function handleApprove() {
        if (!currentPlan || isBusy || destroyed)
            return;

        isBusy = true;
        approveButton.reactive = false;
        rejectButton.reactive = false;

        const planId = currentPlan.plan_id;
        const actionId = currentPlan.proposed_action.action_id;

        try {
            executionStatusLabel.set_text('Approving action...');
            executionStatusLabel.visible = true;

            const approveRes = await approvePlanAction(planId, actionId, true);
            if (destroyed)
                return;

            if (!approveRes.success) {
                executionStatusLabel.set_text(`Approval rejected: ${approveRes.message}`);
                return;
            }

            executionStatusLabel.set_text('Executing diagnostic...');
            const execRes = await executePlanAction(planId, actionId);
            if (destroyed)
                return;

            if (!execRes.success) {
                executionStatusLabel.set_text(`Execution failed: ${execRes.error}`);
                return;
            }

            executionStatusLabel.set_text('Execution completed. Verifying...');
            outputLabel.set_text(execRes.output || '(No output)');
            outputLabel.visible = true;

            const verifyRes = await verifyPlanAction(planId);
            if (destroyed)
                return;

            if (verifyRes.verified) {
                verificationLabel.set_text(`✓ Verified: ${verifyRes.message}`);
                verificationLabel.style_class = 'termiq-verify-success';
            } else {
                verificationLabel.set_text(`✗ Verification: ${verifyRes.message}`);
                verificationLabel.style_class = 'termiq-verify-fail';
            }
            verificationLabel.visible = true;
            executionStatusLabel.set_text('Status: Verified');
        } catch (error) {
            if (!destroyed)
                executionStatusLabel.set_text(`Error: ${error.message}`);
        } finally {
            isBusy = false;
        }
    }

    async function handleReject() {
        if (!currentPlan || isBusy || destroyed)
            return;

        isBusy = true;
        approveButton.reactive = false;
        rejectButton.reactive = false;

        try {
            await approvePlanAction(
                currentPlan.plan_id,
                currentPlan.proposed_action.action_id,
                false
            );
            if (destroyed)
                return;

            executionStatusLabel.set_text('Action rejected by user.');
            executionStatusLabel.visible = true;
            outputLabel.visible = false;
            verificationLabel.visible = false;
        } catch (error) {
            if (!destroyed)
                executionStatusLabel.set_text(`Error: ${error.message}`);
        } finally {
            isBusy = false;
        }
    }

    // ── File Copilot Plan & Execution Logic ────────────────────────
    function renderFileTaskUI(task) {
        currentFileTask = task;

        fileClarifyContainer.visible = false;
        fileTargetDetailsBox.visible = false;
        fileConflictBanner.visible = false;
        filePreviewBox.visible = false;
        fileActionBtnBox.visible = false;
        fileExecutionProgressLabel.visible = false;
        fileVerificationBanner.visible = false;

        // Needs Clarification
        if (task.status === 'needs_clarification') {
            const q = task.clarification_questions.length > 0
                ? task.clarification_questions[0]
                : 'Please specify the missing filename or destination.';
            fileClarifyQuestionLabel.set_text(q);
            fileClarifyAnswerEntry.set_text('');
            fileClarifyContainer.visible = true;
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                if (!destroyed)
                    global.stage.set_key_focus(fileClarifyAnswerEntry);
                return GLib.SOURCE_REMOVE;
            });
            return;
        }

        // Conflict check
        if (task.conflict_detected) {
            fileConflictBanner.set_text(`⚠️ Conflict: ${task.conflict_message || 'Target already exists.'}`);
            fileConflictBanner.visible = true;
            fileTargetDetailsBox.visible = true;
            return;
        }

        // Ready for review / Awaiting approval
        if (task.status === 'awaiting_approval' || task.status === 'ready_for_review') {
            fileTargetDetailsBox.visible = true;
            filePathBadge.set_text(`Target: ${task.target_path || task.target_name}`);
            fileSummaryLabel.set_text(task.summary || 'Review planned file operations before approval.');

            if (task.planned_files && task.planned_files.length > 0) {
                const sample = task.planned_files[0];
                const previewSnippet = sample.content.length > 300
                    ? sample.content.slice(0, 300) + '\n... [Remaining content verified]'
                    : sample.content;
                filePreviewHeaderLabel.set_text(`Preview: ${sample.relative_path} (${sample.size_bytes}B)`);
                filePreviewContentLabel.set_text(previewSnippet);
                filePreviewBox.visible = true;
            }

            fileApproveBtn.reactive = true;
            fileCancelBtn.reactive = true;
            fileActionBtnBox.visible = true;
        }
    }

    async function handleFilePlan() {
        if (isBusy || destroyed)
            return;

        const reqText = fileRequestEntry.get_text().trim();
        if (!reqText)
            return;

        isBusy = true;
        filePlanButton.reactive = false;
        fileRequestEntry.reactive = false;

        try {
            const task = await createFileTask(reqText);
            if (destroyed)
                return;
            renderFileTaskUI(task);
            recentTaskRow.set_text(`File Plan: ${task.target_name || task.operation}`);
        } catch (error) {
            if (!destroyed) {
                fileConflictBanner.set_text(`Error planning request: ${error.message}`);
                fileConflictBanner.visible = true;
                fileTargetDetailsBox.visible = true;
            }
        } finally {
            isBusy = false;
            filePlanButton.reactive = true;
            fileRequestEntry.reactive = true;
        }
    }

    async function handleFileClarifySubmit() {
        if (!currentFileTask || isBusy || destroyed)
            return;

        const answer = fileClarifyAnswerEntry.get_text().trim();
        if (!answer)
            return;

        isBusy = true;
        fileClarifySubmitBtn.reactive = false;

        const fieldKey = (currentFileTask.clarification_fields_needed && currentFileTask.clarification_fields_needed.length > 0)
            ? currentFileTask.clarification_fields_needed[0]
            : 'answer';

        try {
            const res = await clarifyFileTask(currentFileTask.task_id, { [fieldKey]: answer }, answer);
            if (destroyed)
                return;
            renderFileTaskUI(res.task);
        } catch (error) {
            if (!destroyed) {
                fileClarifyQuestionLabel.set_text(`Error submitting answer: ${error.message}`);
            }
        } finally {
            isBusy = false;
            fileClarifySubmitBtn.reactive = true;
        }
    }

    async function handleFileApprove() {
        if (!currentFileTask || isBusy || destroyed)
            return;

        isBusy = true;
        fileApproveBtn.reactive = false;
        fileCancelBtn.reactive = false;

        try {
            fileExecutionProgressLabel.set_text('1/2 Approving file plan...');
            fileExecutionProgressLabel.visible = true;

            const appRes = await approveFileTask(currentFileTask.task_id, true, currentFileTask.approval_token);
            if (destroyed)
                return;

            if (!appRes.success) {
                fileExecutionProgressLabel.set_text(`Approval rejected: ${appRes.message}`);
                return;
            }

            fileExecutionProgressLabel.set_text('2/2 Creating file(s) and verifying...');
            const execRes = await executeFileTask(currentFileTask.task_id, currentFileTask.approval_token);
            if (destroyed)
                return;

            if (!execRes.success) {
                fileExecutionProgressLabel.set_text(`Execution failed: ${execRes.message || 'Error creating files'}`);
                return;
            }

            fileVerificationBanner.set_text(`✓ Verified: ${execRes.task.verification_result || 'Operation completed successfully.'}`);
            fileVerificationBanner.visible = true;
            fileExecutionProgressLabel.set_text('Status: Completed & verified');
            fileActionBtnBox.visible = false;
            recentTaskRow.set_text(`Verified: ${execRes.task.target_name}`);
        } catch (error) {
            if (!destroyed)
                fileExecutionProgressLabel.set_text(`Execution error: ${error.message}`);
        } finally {
            isBusy = false;
        }
    }

    async function handleFileCancel() {
        if (!currentFileTask || isBusy || destroyed)
            return;

        isBusy = true;
        fileApproveBtn.reactive = false;
        fileCancelBtn.reactive = false;

        try {
            await approveFileTask(currentFileTask.task_id, false);
            if (destroyed)
                return;

            fileExecutionProgressLabel.set_text('Operation cancelled.');
            fileExecutionProgressLabel.visible = true;
            fileActionBtnBox.visible = false;
            recentTaskRow.set_text('File operation cancelled.');
        } catch (error) {
            if (!destroyed)
                fileExecutionProgressLabel.set_text(`Cancel failed: ${error.message}`);
        } finally {
            isBusy = false;
        }
    }

    // ── Signal Connections ─────────────────────────────────────────
    askButton.connect('clicked', () => submitQuestion());
    questionEntry.get_clutter_text().connect('activate', () => submitQuestion());
    approveButton.connect('clicked', () => handleApprove());
    rejectButton.connect('clicked', () => handleReject());

    filePlanButton.connect('clicked', () => handleFilePlan());
    fileRequestEntry.get_clutter_text().connect('activate', () => handleFilePlan());
    fileClarifySubmitBtn.connect('clicked', () => handleFileClarifySubmit());
    fileClarifyAnswerEntry.get_clutter_text().connect('activate', () => handleFileClarifySubmit());
    fileApproveBtn.connect('clicked', () => handleFileApprove());
    fileCancelBtn.connect('clicked', () => handleFileCancel());

    indicator.menu.connect('open-state-changed', (_menu, isOpen) => {
        if (isOpen && !destroyed) {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                if (!destroyed) {
                    if (activeMode === 'file')
                        global.stage.set_key_focus(fileRequestEntry);
                    else
                        global.stage.set_key_focus(questionEntry);
                }
                return GLib.SOURCE_REMOVE;
            });
        }
    });

    indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
    indicator.menu.addAction('Refresh system stats', () => refreshStats());

    // Initial metrics request and periodic refresh
    refreshStats();
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

    indicator.connect('destroy', () => {
        destroyed = true;
        if (timerId !== null) {
            GLib.source_remove(timerId);
            timerId = null;
        }
    });

    return indicator;
}
