# Clash AutoLoot – Release Notes

## Window & Stability

- **Window handle fix** – Re-finds the Clash of Clans window each time farming starts, so closing and reopening the game no longer breaks the bot.
- **Faster Stop** – Stop is checked during long operations (troop deployment, waits, etc.), so the bot stops within seconds instead of waiting for the current action to finish.
- **Error handling** – All bot exceptions are caught and shown in the app instead of silently crashing.

## Star Bonus

- **Star Bonus switch** – Replaced the button with a switch under "Auto Upgrade Walls".
- **Completion logic** – Star Bonus mode ends when the empty star is no longer visible on the home screen (star bonus claimed), instead of when "Okay" is clicked.
- **Timer behavior** – Duration field and preset buttons are disabled and greyed out when Star Bonus is on.

## UI (CustomTkinter)

- **CustomTkinter** – Switched from tkinter/ttk to CustomTkinter.
- **Layout** – Card-style sections, dark theme, blue accents.
- **Attack method** – Valkyries is first and default; Sneaky Goblins and Super Minions follow.
- **Time presets** – Star Bonus, 5m, 10m, 20m; default duration is 15 minutes.
- **Duration input** – Only digits allowed, max 3 digits (1–999).
- **Completion feedback** – Plays a Windows sound when the bot finishes successfully instead of a popup.
- **Error preview** – Errors are shown in the status bar and in a messagebox.

## Logging

- **Log level** – Only errors are logged; info and debug messages are suppressed.
- **Error display** – Errors shown in the status bar and in a messagebox.
