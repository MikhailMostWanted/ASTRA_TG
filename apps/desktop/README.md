# Astra Desktop

Локальный macOS desktop-клиент для Astra поверх Tauri + React + TypeScript.

Быстрые команды из корня репозитория:

```bash
astratg desktop
astratg desktop-build
astratg desktop-install
astratg desktop-open
astratg desktop-stop
```

Где лежит `.app`:

- локальная сборка: `var/desktop/Astra Desktop.app`
- установленное приложение: `~/Applications/Astra Desktop.app`

Для пересборки иконок:

```bash
./apps/desktop/scripts/generate-macos-icons.sh
```
