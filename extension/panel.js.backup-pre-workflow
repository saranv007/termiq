
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import { getSystemSummary, askTermiq } from './api.js';

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

    // Assistant section
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
    questionEntry.set_width(250);

    const askButton = new St.Button({
        label: 'Ask',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });

    const questionRow = new PopupMenu.PopupBaseMenuItem({
        reactive: false,
        can_focus: false,
    });

    const questionBox = new St.BoxLayout({
        vertical: false,
        x_expand: true,
    });

    questionBox.add_child(questionEntry);
    questionBox.add_child(askButton);
    questionRow.add_child(questionBox);
    indicator.menu.addMenuItem(questionRow);

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

    // Fetch live system metrics
    async function refreshStats() {
        try {
            const data = await getSystemSummary();

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
            connectionLabel.set_text('Backend: Offline');
            console.error('TERMIQ system summary error:', error);
        }
    }

    // Send question to the existing FastAPI endpoint
    async function submitQuestion() {
        const question = questionEntry.get_text().trim();

        if (!question) {
            answerLabel.set_text('Please type a question first.');
            return;
        }

        askButton.reactive = false;
        answerLabel.set_text('TERMIQ is processing your question...');

        try {
            const response = await askTermiq(question);
            answerLabel.set_text(extractAnswer(response));
        } catch (error) {
            answerLabel.set_text(`Request failed: ${error.message}`);
            console.error('TERMIQ assistant error:', error);
        } finally {
            askButton.reactive = true;
        }
    }

    askButton.connect('clicked', () => {
        submitQuestion();
    });

    questionEntry.get_clutter_text().connect('activate', () => {
        submitQuestion();
    });

    // Focus the input when the dropdown opens
    indicator.menu.connect('open-state-changed', (_menu, isOpen) => {
        if (isOpen) {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
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

    refreshStats();

    const timerId = GLib.timeout_add_seconds(
        GLib.PRIORITY_DEFAULT,
        5,
        () => {
            refreshStats();
            return GLib.SOURCE_CONTINUE;
        }
    );

    indicator.connect('destroy', () => {
        GLib.source_remove(timerId);
    });

    return indicator;
}
