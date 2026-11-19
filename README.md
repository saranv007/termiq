1. Start TERMIQ backend automatically
systemctl --user daemon-reload
systemctl --user enable --now termiq-backend.service


2. Enable the GNOME extension
gnome-extensions enable termiq@local


3. Check installation
systemctl --user status termiq-backend.service --no-pager
gnome-extensions info termiq@local


4. Test backend
curl http://127.0.0.1:8765/health


Expected:
{"status":"ok","application":"TERMIQ","version":"2.0.0"}


5. View backend logs if something fails
journalctl --user -u termiq-backend.service -f
