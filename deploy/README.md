# Сходня как сервис

## LXC / сервер (systemd, нужен root)

```bash
sudo ./deploy/install.sh
```

Скрипт создаёт системного пользователя `skhodnya`, копирует проект в `/opt/skhodnya`,
ставит unit `/etc/systemd/system/skhodnya.service`, включает автозапуск и стартует.

Параметры:

```bash
sudo HOST=0.0.0.0 PORT=9000 ./deploy/install.sh      # доступ из локальной сети
sudo DEST=/srv/skhodnya ./deploy/install.sh          # другой каталог
```

По умолчанию сервер слушает `127.0.0.1:8080` — снаружи не виден. Для доступа
с других устройств используйте `HOST=0.0.0.0`, но только в доверенной сети или
за VPN: у Сходни нет авторизации.

Проверка и логи:

```bash
systemctl status skhodnya
journalctl -u skhodnya -f
curl -s http://127.0.0.1:8080/api/config
```

## Ноутбук (пользовательский unit, без root)

```bash
cp deploy/skhodnya-user.service ~/.config/systemd/user/skhodnya.service
# поправьте WorkingDirectory в файле на свой путь
systemctl --user daemon-reload
systemctl --user enable --now skhodnya
loginctl enable-linger "$USER"   # автозапуск без входа в систему
```

## Папка закладок

Путь хранится в `/opt/skhodnya/config.json` и меняется в настройках приложения.
Если выбираете папку вне `/opt/skhodnya/data`, добавьте её в `ReadWritePaths`
юнита и перезапустите сервис:

```ini
ReadWritePaths=/opt/skhodnya/data /opt/skhodnya/config.json /srv/bookmarks
```

## Обновление

```bash
git pull
sudo ./deploy/install.sh
```

Скрипт обновляет код, темы и модули, но **не перезаписывает `data/`** — закладки
остаются на месте. При первой установке демо-данные копируются из репозитория.

## Проверки ping

`ping` требует `CAP_NET_RAW`. В системном unit это выдано точечно:

```ini
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW
```

Root сервису не нужен. Если политика запрещает capabilities — используйте в
проверках `tcp`/`http` вместо `ping`.

## Бэкап

Всё состояние — папка `data/`:

```bash
tar czf skhodnya-data-$(date +%F).tgz -C /opt/skhodnya data
```

## Удаление

```bash
sudo systemctl disable --now skhodnya
sudo rm /etc/systemd/system/skhodnya.service
sudo systemctl daemon-reload
sudo rm -rf /opt/skhodnya
sudo userdel skhodnya
```
