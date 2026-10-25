
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {createTermiqPanel} from './panel.js';

export default class TermiqExtension extends Extension {
    enable() {
        this._indicator = createTermiqPanel();
        Main.panel.addToStatusArea('termiq', this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
