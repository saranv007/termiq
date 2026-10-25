
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import { getSystemSummary } from './api.js';

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
        });

        item.add_child(label);
        indicator.menu.addMenuItem(item);

        return label;
    }

    const cpuLabel = addStatusRow('CPU: Loading...');
    const memoryLabel = addStatusRow('RAM: Loading...');
    const diskLabel = addStatusRow('Disk: Loading...');
    const connectionLabel = addStatusRow('Backend: Connecting...');

    async function refreshStats() {
        try {
            const data = await getSystemSummary();

            cpuLabel.set_text(
                `CPU usage: ${data.cpu.usage_percent.toFixed(1)}%`
            );

            memoryLabel.set_text(
                `RAM: ${data.memory.used_percent.toFixed(1)}% used`
            );

            diskLabel.set_text(
                `Disk: ${data.disk.used_percent.toFixed(1)}% used`
            );

            connectionLabel.set_text('Backend: Connected');
        } catch (error) {
            connectionLabel.set_text('Backend: Offline');

            console.error(
                'TERMIQ system summary error:',
                error
            );
        }
    }

    indicator.menu.addMenuItem(
        new PopupMenu.PopupSeparatorMenuItem()
    );

    indicator.menu.addAction(
        'Refresh system stats',
        () => refreshStats()
    );

    // Fetch immediately when the extension starts.
    refreshStats();

    // Update the metrics every 5 seconds.
    const timerId = GLib.timeout_add_seconds(
        GLib.PRIORITY_DEFAULT,
        5,
        () => {
            refreshStats();
            return GLib.SOURCE_CONTINUE;
        }
    );

    // Clean up the timer when the extension is destroyed.
    indicator.connect('destroy', () => {
        GLib.source_remove(timerId);
    });

    return indicator;
}
