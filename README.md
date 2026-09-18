# Work Journal

Work Journal is a minimalist Windows desktop app that reminds you at selected
intervals to log what you are currently doing. It runs quietly in the system
tray, stores entries locally, and provides a simple overview of your workday.

## Features

- Configurable check-in interval from 1 to 240 minutes
- Lightweight animated check-in prompt
- Keyboard controls: `Enter` to log and `Esc` to skip
- Background operation through the Windows system tray
- Local activity history with CSV export
- No third-party Python packages required

## Requirements

- Windows 10 or Windows 11
- Python 3.9 or newer available on `PATH`

## Run

Double-click `run_work_journal.bat`, or run:

```powershell
python work_journal.py
```

In the custom title bar, `-` hides the app to the system tray while keeping the
timer active. `×` exits the app and stops the timer. Use the tray icon to reopen
the main window.

## Local data

Work Journal creates these files next to the app:

- `work_journal_config.json` stores the selected interval.
- `work_journal_log.csv` stores activity entries.

Both files are excluded from Git so personal activity data is not published.
The local `Work Journal.lnk` shortcut is also excluded because it contains a
machine-specific path.

## License

MIT
