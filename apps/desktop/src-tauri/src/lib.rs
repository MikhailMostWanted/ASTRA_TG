use serde::{Deserialize, Serialize};
use std::{
    env,
    fs::{self, OpenOptions},
    io::Write,
    net::{TcpStream, ToSocketAddrs},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, Instant},
};
use tauri::{Manager, RunEvent, State};

const APP_NAME: &str = "Astra Desktop";

struct DesktopRuntimeState {
    owned_bridge: Mutex<Option<Child>>,
}

impl Default for DesktopRuntimeState {
    fn default() -> Self {
        Self {
            owned_bridge: Mutex::new(None),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DesktopLaunchStatus {
    api_url: String,
    repo_root: String,
    config_path: String,
    log_path: String,
    status: String,
    detail: String,
    owned_bridge: bool,
}

#[derive(Debug, Clone, Deserialize)]
struct DesktopLauncherConfig {
    #[serde(alias = "appName")]
    app_name: String,
    #[serde(alias = "repoRoot")]
    repo_root: String,
    #[serde(alias = "pythonExecutable")]
    python_executable: String,
    #[serde(alias = "apiUrl")]
    api_url: String,
    #[serde(alias = "apiHost")]
    api_host: String,
    #[serde(alias = "apiPort")]
    api_port: u16,
    #[serde(alias = "pidPath")]
    pid_path: String,
    #[serde(alias = "logPath")]
    log_path: String,
}

#[tauri::command]
fn prepare_desktop_launch(state: State<'_, DesktopRuntimeState>) -> Result<DesktopLaunchStatus, String> {
    let config_path = desktop_launcher_config_path();
    let config = read_launcher_config(&config_path)?;
    append_launcher_log(
        &config.log_path,
        &format!(
            "prepare_desktop_launch called; repo_root={}, api_url={}",
            config.repo_root, config.api_url
        ),
    );

    if config.app_name != APP_NAME {
        append_launcher_log(
            &config.log_path,
            &format!("launcher config app_name mismatch: {}", config.app_name),
        );
        return Err(format!(
            "Launcher config повреждён: ожидалось имя {}, найдено {}",
            APP_NAME, config.app_name
        ));
    }

    if !Path::new(&config.repo_root).exists() {
        append_launcher_log(
            &config.log_path,
            &format!("repo_root missing: {}", config.repo_root),
        );
        return Err(format!(
            "Репозиторий из launcher config не найден: {}. Повтори astratg desktop-build или astratg desktop-install.",
            config.repo_root
        ));
    }

    if bridge_is_healthy(&config) {
        append_launcher_log(&config.log_path, "bridge already healthy; connecting");
        return Ok(DesktopLaunchStatus {
            api_url: config.api_url.clone(),
            repo_root: config.repo_root.clone(),
            config_path: config_path.display().to_string(),
            log_path: config.log_path.clone(),
            status: String::from("connected"),
            detail: String::from("Подключено к уже запущенному desktop bridge."),
            owned_bridge: false,
        });
    }

    if let Some(pid) = read_pid(Path::new(&config.pid_path)) {
        if pid_exists(pid) && wait_for_bridge(&config, Duration::from_secs(4)) {
            append_launcher_log(
                &config.log_path,
                &format!("bridge pid {pid} already exists and became healthy"),
            );
            return Ok(DesktopLaunchStatus {
                api_url: config.api_url.clone(),
                repo_root: config.repo_root.clone(),
                config_path: config_path.display().to_string(),
                log_path: config.log_path.clone(),
                status: String::from("connected"),
                detail: String::from("Bridge уже запускался и успел подняться."),
                owned_bridge: false,
            });
        }
    }

    append_launcher_log(&config.log_path, "starting owned bridge process");
    let child = spawn_bridge_process(&config).map_err(|error| {
        append_launcher_log(
            &config.log_path,
            &format!("failed to spawn bridge: {error}"),
        );
        format!(
            "Не удалось поднять desktop bridge. {}\nЛог: {}",
            error, config.log_path
        )
    })?;

    {
        let mut owned = state
            .owned_bridge
            .lock()
            .map_err(|_| String::from("Не удалось захватить состояние desktop runtime."))?;
        if let Some(mut existing) = owned.take() {
            let _ = existing.kill();
            let _ = existing.wait();
        }
        *owned = Some(child);
    }

    if wait_for_bridge(&config, Duration::from_secs(14)) {
        append_launcher_log(&config.log_path, "owned bridge is healthy");
        return Ok(DesktopLaunchStatus {
            api_url: config.api_url.clone(),
            repo_root: config.repo_root.clone(),
            config_path: config_path.display().to_string(),
            log_path: config.log_path.clone(),
            status: String::from("started"),
            detail: String::from("Bridge поднят самим приложением."),
            owned_bridge: true,
        });
    }

    stop_owned_bridge(&state);
    append_launcher_log(&config.log_path, "owned bridge failed to become healthy in time");
    Err(format!(
        "Bridge не поднялся вовремя. Проверь локальный Python runtime и лог: {}",
        config.log_path
    ))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(DesktopRuntimeState::default())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .invoke_handler(tauri::generate_handler![prepare_desktop_launch])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| match event {
            RunEvent::Exit | RunEvent::ExitRequested { .. } => {
                if let Some(state) = app_handle.try_state::<DesktopRuntimeState>() {
                    stop_owned_bridge(&state);
                }
            }
            _ => {}
        });
}

fn desktop_launcher_config_path() -> PathBuf {
    home_dir()
        .join("Library")
        .join("Application Support")
        .join(APP_NAME)
        .join("launcher.json")
}

fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn read_launcher_config(path: &Path) -> Result<DesktopLauncherConfig, String> {
    let content = fs::read_to_string(path).map_err(|error| {
        format!(
            "Не удалось прочитать launcher config {}: {}",
            path.display(),
            error
        )
    })?;
    serde_json::from_str::<DesktopLauncherConfig>(&content).map_err(|error| {
        format!(
            "Не удалось прочитать launcher config {}: {}",
            path.display(),
            error
        )
    })
}

fn bridge_is_healthy(config: &DesktopLauncherConfig) -> bool {
    let mut addresses = match (config.api_host.as_str(), config.api_port).to_socket_addrs() {
        Ok(addresses) => addresses,
        Err(_) => return false,
    };

    if let Some(address) = addresses.next() {
        return TcpStream::connect_timeout(&address, Duration::from_millis(350)).is_ok();
    }

    false
}

fn wait_for_bridge(config: &DesktopLauncherConfig, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if bridge_is_healthy(config) {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    false
}

fn spawn_bridge_process(config: &DesktopLauncherConfig) -> Result<Child, String> {
    let log_path = PathBuf::from(&config.log_path);
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent).map_err(|error| {
            format!("Не удалось создать каталог логов {}: {}", parent.display(), error)
        })?;
    }

    let mut log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("Не удалось открыть лог {}: {}", log_path.display(), error))?;

    let launch_stamp = format!(
        "\n=== Astra Desktop launch {} ===\n",
        chrono_like_timestamp()
    );
    let _ = log_file.write_all(launch_stamp.as_bytes());

    let stdout = log_file
        .try_clone()
        .map_err(|error| format!("Не удалось клонировать log handle: {}", error))?;

    Command::new(&config.python_executable)
        .args([
            "-m",
            "apps.desktop_api",
            "--host",
            &config.api_host,
            "--port",
            &config.api_port.to_string(),
        ])
        .current_dir(&config.repo_root)
        .env("ASTRA_DESKTOP_API_PID_PATH", &config.pid_path)
        .stdin(Stdio::null())
        .stdout(Stdio::from(stdout))
        .stderr(Stdio::from(log_file))
        .spawn()
        .map_err(|error| {
            format!(
                "Не удалось запустить {} из {} через {}: {}",
                config.api_url, config.repo_root, config.python_executable, error
            )
        })
}

fn stop_owned_bridge(state: &State<'_, DesktopRuntimeState>) {
    if let Ok(mut owned) = state.owned_bridge.lock() {
        if let Some(mut child) = owned.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn append_launcher_log(log_path: &str, message: &str) {
    let path = PathBuf::from(log_path);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }

    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let line = format!("[launcher {}] {message}\n", chrono_like_timestamp());
        let _ = file.write_all(line.as_bytes());
    }
}

fn read_pid(path: &Path) -> Option<u32> {
    let raw = fs::read_to_string(path).ok()?;
    raw.trim().parse::<u32>().ok()
}

fn pid_exists(pid: u32) -> bool {
    Command::new("ps")
        .args(["-p", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn chrono_like_timestamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};

    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_else(|_| Duration::from_secs(0))
        .as_secs();
    format!("unix:{seconds}")
}
