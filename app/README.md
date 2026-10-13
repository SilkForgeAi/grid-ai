# Grid desktop shell (Tauri) - prototype

The real app is now `grid app`: a local server plus a browser UI (see the main README).
This Tauri shell is kept for a future native wrapper. The plan is for it to start `grid app --no-browser`,
read the sign-in URL it prints, and load that URL in its window. `ui/index.html` here is the original
mock-up and is not wired to the agent.
