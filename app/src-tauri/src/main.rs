// Grid AI — Tauri desktop shell.
//
// The shell is deliberately thin: all the intelligence lives in the Python core
// (the `grid` package). This process launches a task against that core and
// streams the agent's output back to the web UI as Tauri events, so the front
// end can render the terminal, confidence badges, and diffs live.
//
// Architecture: UI (ui/index.html)  <—events/invoke—>  this Rust shell
//               this shell           <—stdout lines—>   `python -m grid.cli`
//
// Phase 2 will replace the one-shot CLI spawn with a long-lived local websocket
// service so confirmations (the RED gate) can round-trip interactively.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use tauri::{Emitter, Window};

#[derive(serde::Serialize, Clone)]
struct Line {
    stream: String, // "stdout" | "stderr" | "system"
    text: String,
}

// Run a Grid AI task. Streams each output line to the UI as a `grid://line`
// event; resolves when the process exits.
#[tauri::command]
fn run_grid_task(window: Window, task: String, depth: String, workspace: String) -> Result<i32, String> {
    let mut child = Command::new("python")
        .args(["-m", "grid.cli", &task, "--depth", &depth, "--workspace", &workspace])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start grid core: {e}"))?;

    if let Some(out) = child.stdout.take() {
        let w = window.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                let _ = w.emit("grid://line", Line { stream: "stdout".into(), text: line });
            }
        });
    }
    if let Some(err) = child.stderr.take() {
        let w = window.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                let _ = w.emit("grid://line", Line { stream: "stderr".into(), text: line });
            }
        });
    }

    let status = child.wait().map_err(|e| format!("grid core crashed: {e}"))?;
    Ok(status.code().unwrap_or(-1))
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![run_grid_task])
        .run(tauri::generate_context!())
        .expect("error while running Grid AI");
}
