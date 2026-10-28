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

    // ── System Monitor Section ─────────────────────────────────────
    const cpuLabel = addStatusRow('CPU: Loading...');
    const memoryLabel = addStatusRow('RAM: Loading...');
    const diskLabel = addStatusRow('Disk: Loading...');
    const connectionLabel = addStatusRow('Backend: Connecting...');

    indicator.menu.addMenuItem(
        new PopupMenu.PopupSeparatorMenuItem()
    );

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

    // Diagnostic Evidence item (create first, then hide)
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
        text: 'Type a question and press Ask.',
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
    });
    answerLabel.set_style('max-width: 320px;');
    answerLabel.get_clutter_text().set_line_wrap(true);
    answerItem.add_child(answerLabel);
    indicator.menu.addMenuItem(answerItem);

    // System Diagnostic Plan item (create first, then hide)
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
    // FILE & FOLDER COPILOT SECTION (V2.0)
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

    // Plan Review & Approval Container
    const filePlanReviewBox = new St.BoxLayout({
        vertical: true,
        x_expand: true,
        style_class: 'termiq-plan-box',
        visible: false,
    });

    const fileSummaryLabel = new St.Label({
        text: '',
        style_class: 'termiq-plan-title',
    });
    fileSummaryLabel.set_style('max-width: 320px;');
    fileSummaryLabel.get_clutter_text().set_line_wrap(true);

    const fileDestBadge = new St.Label({
        text: '',
        style_class: 'termiq-path-badge',
    });
    fileDestBadge.set_style('max-width: 320px;');
    fileDestBadge.get_clutter_text().set_line_wrap(true);

    const fileConflictBanner = new St.Label({
        text: '',
        style_class: 'termiq-conflict-text',
        visible: false,
    });
    fileConflictBanner.set_style('max-width: 320px;');
    fileConflictBanner.get_clutter_text().set_line_wrap(true);

    const filePreviewSnippet = new St.Label({
        text: '',
        style_class: 'termiq-file-preview',
        visible: false,
    });
    filePreviewSnippet.set_style('max-width: 320px;');
    filePreviewSnippet.get_clutter_text().set_line_wrap(true);

    const fileActionBtnBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
        style: 'spacing: 8px; margin-top: 6px;',
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

    filePlanReviewBox.add_child(fileSummaryLabel);
    filePlanReviewBox.add_child(fileDestBadge);
    filePlanReviewBox.add_child(fileConflictBanner);
    filePlanReviewBox.add_child(filePreviewSnippet);
    filePlanReviewBox.add_child(fileActionBtnBox);
    filePlanReviewBox.add_child(fileExecutionProgressLabel);
    filePlanReviewBox.add_child(fileVerificationBanner);

    fileContainer.add_child(fileHeaderLabel);
    fileContainer.add_child(fileInputBox);
    fileContainer.add_child(fileClarifyContainer);
    fileContainer.add_child(filePlanReviewBox);

    fileSectionItem.add_child(fileContainer);
    indicator.menu.addMenuItem(fileSectionItem);

    // ── Shared State Tracking ──────────────────────────────────────
    let activeMode = 'system'; // 'system' or 'file'
    let currentPlan = null;
    let currentFileTask = null;
    let isBusy = false;
    let destroyed = false;
    let timerId = null;

    // ── Mode Switcher Handlers ─────────────────────────────────────
    function setMode(mode) {
        if (destroyed)
            return;

        activeMode = mode;
        if (mode === 'system') {
            sysModeBtn.style_class = 'termiq-mode-btn-active';
            fileModeBtn.style_class = 'termiq-mode-btn';

            fileSectionItem.visible = false;

            sysHeaderLabel.visible = true;
            questionRow.visible = true;
            answerItem.visible = true;
            if (evidenceLabel.text)
                evidenceItem.visible = true;
            if (currentPlan)
                planItem.visible = true;
        } else {
            fileModeBtn.style_class = 'termiq-mode-btn-active';
            sysModeBtn.style_class = 'termiq-mode-btn';

            sysHeaderLabel.visible = false;
            questionRow.visible = false;
            answerItem.visible = false;
            evidenceItem.visible = false;
            planItem.visible = false;

            fileSectionItem.visible = true;
        }
    }

    sysModeBtn.connect('clicked', () => setMode('system'));
    fileModeBtn.connect('clicked', () => setMode('file'));

    // ── System Copilot Logic ───────────────────────────────────────
    async function refreshStats() {
        if (destroyed)
            return;

        try {
            const data = await getSystemSummary();
            if (destroyed)
                return;

            cpuLabel.set_text(`CPU usage: ${Number(data.cpu.usage_percent).toFixed(1)}%`);
            memoryLabel.set_text(`RAM: ${Number(data.memory.used_percent).toFixed(1)}% used`);
            diskLabel.set_text(`Disk: ${Number(data.disk.used_percent).toFixed(1)}% used`);
            connectionLabel.set_text('Backend: Connected');
        } catch (error) {
            if (!destroyed)
                connectionLabel.set_text('Backend: Offline');
        }
    }

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

        answerLabel.set_text('TERMIQ is diagnosing your system and consulting AI...');

        try {
            const response = await askTermiq(question);
            if (destroyed)
                return;

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

            if (response.plan && response.plan.proposed_action) {
                const action = response.plan.proposed_action;
                currentPlan = {
                    planId: response.plan.plan_id,
                    actionId: action.action_id,
                    actionType: action.action_type,
                    riskLevel: action.risk_level || 'safe',
                };

                planTitleLabel.set_text(`Proposed Action: ${action.action_type}`);
                planDescLabel.set_text(action.description || 'Run system diagnostic');

                const isSafe = action.risk_level === 'safe';
                planRiskLabel.set_text(`Risk: ${action.risk_level || 'safe'} — Explicit approval required`);
                planRiskLabel.style_class = isSafe ? 'termiq-plan-badge-safe' : 'termiq-plan-badge-warn';

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
            if (!destroyed)
                answerLabel.set_text(`Request failed: ${error.message}`);
        } finally {
            isBusy = false;
            if (!destroyed)
                askButton.reactive = true;
        }
    }

    async function handleApprove() {
        if (!currentPlan || isBusy || destroyed)
            return;

        isBusy = true;
        approveButton.reactive = false;
        rejectButton.reactive = false;

        executionStatusLabel.set_text('1/3 Submitting user approval...');
        executionStatusLabel.visible = true;

        try {
            const approveResult = await approvePlanAction(currentPlan.planId, currentPlan.actionId, true);
            if (destroyed)
                return;

            if (!approveResult.success) {
                executionStatusLabel.set_text(`Approval rejected: ${approveResult.message || 'Not approved'}`);
                return;
            }

            executionStatusLabel.set_text('2/3 Executing approved diagnostic...');
            const execResult = await executePlanAction(currentPlan.planId, currentPlan.actionId);
            if (destroyed)
                return;

            if (!execResult.success) {
                executionStatusLabel.set_text(`Execution failed: ${execResult.error || 'Unknown error'}`);
                return;
            }

            if (execResult.stdout) {
                const preview = execResult.stdout.trim().split('\n').slice(0, 6).join('\n');
                outputLabel.set_text(preview || '(Empty output)');
                outputLabel.visible = true;
            } else if (execResult.stderr) {
                outputLabel.set_text(`stderr: ${execResult.stderr.trim().slice(0, 200)}`);
                outputLabel.visible = true;
            }

            executionStatusLabel.set_text('3/3 Verifying execution result...');
            const verifyResult = await verifyPlanAction(currentPlan.planId);
            if (destroyed)
                return;

            if (verifyResult.verified) {
                verificationLabel.set_text(`Result Verified: ${verifyResult.detail}`);
                verificationLabel.style_class = 'termiq-verify-success';
                executionStatusLabel.set_text('Status: Executed and verified');
            } else {
                verificationLabel.set_text(`Verification notice: ${verifyResult.detail}`);
                verificationLabel.style_class = 'termiq-verify-fail';
                executionStatusLabel.set_text('Status: Completed with verification notice');
            }
            verificationLabel.visible = true;
            buttonBox.visible = false;
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
            await approvePlanAction(currentPlan.planId, currentPlan.actionId, false);
            if (destroyed)
                return;

            executionStatusLabel.set_text('Action rejected by user.');
            executionStatusLabel.visible = true;
            buttonBox.visible = false;
        } catch (error) {
            if (!destroyed)
                executionStatusLabel.set_text(`Rejection failed: ${error.message}`);
        } finally {
            isBusy = false;
        }
    }

    // ── File Copilot Logic (V2.0) ──────────────────────────────────
    function renderFileTask(task) {
        if (destroyed || !task)
            return;

        currentFileTask = task;

        // Reset display widgets
        fileClarifyContainer.visible = false;
        filePlanReviewBox.visible = false;
        fileConflictBanner.visible = false;
        filePreviewSnippet.visible = false;
        fileExecutionProgressLabel.visible = false;
        fileVerificationBanner.visible = false;

        // 1. Needs clarification state
        if (task.status === 'needs_clarification' && task.clarification_questions.length > 0) {
            fileClarifyQuestionLabel.set_text(task.clarification_questions.join('\n'));
            fileClarifyAnswerEntry.set_text('');
            fileClarifyContainer.visible = true;
            return;
        }

        // 2. Ready for review / awaiting approval
        if (task.status === 'awaiting_approval' || task.status === 'ready_for_review') {
            fileSummaryLabel.set_text(task.summary || `Task: ${task.operation}`);
            fileDestBadge.set_text(task.resolved_target_path || task.target_path || 'Destination pending');

            if (task.conflict_detected) {
                fileConflictBanner.set_text(`⚠ Conflict: ${task.conflict_message || 'Target already exists.'}`);
                fileConflictBanner.visible = true;
                fileActionBtnBox.visible = false;
            } else {
                fileActionBtnBox.visible = true;
                fileApproveBtn.reactive = true;
                fileCancelBtn.reactive = true;
            }

            if (task.planned_files && task.planned_files.length > 0) {
                const first = task.planned_files[0];
                const snippet = first.content.split('\n').slice(0, 5).join('\n');
                filePreviewSnippet.set_text(`Preview (${first.relative_path}):\n${snippet}`);
                filePreviewSnippet.visible = true;
            }

            filePlanReviewBox.visible = true;
        }
    }

    async function handleFilePlan() {
        if (isBusy || destroyed)
            return;

        const requestText = fileRequestEntry.get_text().trim();
        if (!requestText) {
            fileSummaryLabel.set_text('Please describe a file or folder task first.');
            filePlanReviewBox.visible = true;
            return;
        }

        isBusy = true;
        filePlanButton.reactive = false;

        try {
            const task = await createFileTask(requestText);
            renderFileTask(task);
        } catch (error) {
            if (!destroyed) {
                fileSummaryLabel.set_text(`Request failed: ${error.message}`);
                filePlanReviewBox.visible = true;
            }
        } finally {
            isBusy = false;
            if (!destroyed)
                filePlanButton.reactive = true;
        }
    }

    async function handleFileClarifySubmit() {
        if (!currentFileTask || isBusy || destroyed)
            return;

        const answerText = fileClarifyAnswerEntry.get_text().trim();
        if (!answerText)
            return;

        isBusy = true;
        fileClarifySubmitBtn.reactive = false;

        try {
            const field = (currentFileTask.clarification_fields_needed && currentFileTask.clarification_fields_needed[0]) || 'answer';
            const answers = {};
            answers[field] = answerText;

            const res = await clarifyFileTask(currentFileTask.task_id, answers, answerText);
            if (res.task)
                renderFileTask(res.task);
        } catch (error) {
            if (!destroyed)
                fileClarifyQuestionLabel.set_text(`Clarification error: ${error.message}`);
        } finally {
            isBusy = false;
            if (!destroyed)
                fileClarifySubmitBtn.reactive = true;
        }
    }

    async function handleFileApprove() {
        if (!currentFileTask || isBusy || destroyed)
            return;

        isBusy = true;
        fileApproveBtn.reactive = false;
        fileCancelBtn.reactive = false;

        fileExecutionProgressLabel.set_text('1/2 Approving task with server...');
        fileExecutionProgressLabel.visible = true;

        try {
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
