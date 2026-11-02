window.START_PAGE = {
  "id": "home",
  "title": "Дом",
  "subtitle": "всё под рукой",
  "groups": [
    {
      "id": "g-proxmox",
      "title": "Proxmox",
      "items": [
        {
          "id": "i-pve1",
          "title": "PVE 1",
          "url": "https://192.168.0.115:8006",
          "note": "основной гипервизор",
          "tags": [
            "pve",
            "веб"
          ],
          "fav": true,
          "checks": [
            {
              "type": "http",
              "interval": 5
            },
            {
              "type": "ping",
              "interval": 5,
              "host": "192.168.0.115"
            }
          ]
        },
        {
          "id": "i-pve2",
          "title": "PVE 2",
          "url": "https://192.168.3.11:8006",
          "note": "второй узел",
          "tags": [
            "pve",
            "веб"
          ],
          "fav": false,
          "checks": []
        }
      ]
    },
    {
      "id": "g-docker",
      "title": "Docker и сервисы",
      "items": [
        {
          "id": "i-dockge",
          "title": "Dockge",
          "url": "http://192.168.3.10:5001",
          "note": "compose-стеки",
          "tags": [
            "docker"
          ],
          "fav": true,
          "checks": []
        },
        {
          "id": "i-mattermost",
          "title": "Mattermost",
          "url": "https://mattermost.local",
          "note": "чат",
          "tags": [
            "чат"
          ],
          "fav": false,
          "checks": []
        },
        {
          "id": "i-uptime",
          "title": "Uptime Kuma",
          "url": "http://192.168.3.10:3001",
          "note": "статусы сервисов",
          "tags": [
            "мониторинг"
          ],
          "fav": false,
          "checks": []
        }
      ]
    },
    {
      "id": "g-tables",
      "title": "Таблицы",
      "items": [
        {
          "id": "i-sheet1",
          "title": "Таблица — заявки",
          "url": "https://docs.google.com/spreadsheets/d/ЗАМЕНИ_НА_ID/edit",
          "note": "Google Sheets",
          "tags": [
            "sheets",
            "работа"
          ],
          "fav": true,
          "checks": []
        },
        {
          "id": "i-sheet2",
          "title": "Локальный xlsx",
          "url": "file:///home/ankasatikov/Документы/Отчёты/свод.xlsx",
          "note": "открывается как файл",
          "tags": [
            "xlsx"
          ],
          "fav": false,
          "checks": []
        }
      ]
    },
    {
      "id": "g-other",
      "title": "Прочее",
      "items": [
        {
          "id": "i-dude",
          "title": "The Dude",
          "url": "http://192.168.3.10:2210",
          "note": "web-интерфейс, если включён",
          "tags": [
            "сеть"
          ],
          "fav": false,
          "checks": []
        },
        {
          "id": "i-grafana",
          "title": "Grafana",
          "url": "http://192.168.3.10:3000",
          "note": "графики",
          "tags": [
            "мониторинг"
          ],
          "fav": false,
          "checks": []
        }
      ]
    }
  ]
};
