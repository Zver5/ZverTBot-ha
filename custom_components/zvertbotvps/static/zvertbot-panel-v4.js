class ZverTBotVpsPanelV4 extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._rendered = false;
  }

  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _update() {
    if (!this._hass) return;

    const states = this._hass.states || {};
    const allStats = Object.entries(states).filter(
      ([entityId, state]) =>
        entityId.startsWith("sensor.") &&
        state.attributes?.zvertbot_role === "all_stats" &&
        Boolean(state.attributes?.zvertbot_entry_id)
    );

    const servers = allStats.map(([entityId, state]) => {
      const attrs = state.attributes || {};
      const entryId = attrs.zvertbot_entry_id;

      const findByRole = (domain, role) =>
        Object.values(states).find(
          entity =>
            entity.entity_id?.startsWith(`${domain}.`) &&
            entity.attributes?.zvertbot_entry_id === entryId &&
            entity.attributes?.zvertbot_role === role
        ) || null;

      return {
        entityId,
        entryId,
        attrs,
        allStats: state,
        awg: findByRole("sensor", "awg_clients"),
        xray: findByRole("sensor", "xray_clients"),
        connection: findByRole("binary_sensor", "connection"),
        connectionState: findByRole("sensor", "connection_state"),
        refreshButton: findByRole("button", "refresh"),
        reconnectButton: findByRole("button", "reconnect"),
      };
    });

    this._servers = servers;
    this._render();
  }

  _findEntity(states, allStatsEntityId, domain, suffix) {
    const prefix = allStatsEntityId
      .replace(/^sensor\./, "")
      .replace(/_all_stats$/, "");
    return states[`${domain}.${prefix}_${suffix}`] || null;
  }

  _findClientSensor(states, allStatsEntityId, type) {
    const prefix = allStatsEntityId
      .replace(/^sensor\./, "")
      .replace(/_all_stats$/, "");

    const suffix =
      type === "awg"
        ? "_awg_clients"
        : "_xray_clients";

    const entityId = `sensor.${prefix}${suffix}`;

    return states[entityId] || null;
  }

  _render() {
    if (!this._servers?.length) {
      this.shadowRoot.innerHTML = `
        ${this._styles()}
        <div class="empty">VPS не найдены</div>
      `;
      return;
    }

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <div class="servers">
        ${this._servers.map((server, index) =>
          this._renderVps(server, index)
        ).join("")}
      </div>
    `;

    this.shadowRoot.querySelectorAll("button[data-action]").forEach(button => {
      button.addEventListener("click", async () => {
        const entityId = button.dataset.entity;
        if (!entityId || !this._hass) return;
        try {
          await this._hass.callService("button", "press", { entity_id: entityId });
        } catch (err) {
          console.error("ZverTBot VPS action failed", err);
        }
      });
    });
  }

  _renderVps(server, index) {
    const attrs = server.attrs || {};
    const system = attrs.system || {};
    const disk = system.disk || {};
    const services = attrs.services || {};
    const backup = attrs.backup || {};
    const fail2ban = attrs.fail2ban || {};

    const ip =
      attrs.server_ip ||
      attrs.server?.ip ||
      "—";

    const mode = attrs.connection_mode || "—";

    const cpu = system.cpu ?? "—";
    const memory = system.memory_percent ?? "—";
    const diskPercent = disk.percent ?? "—";
    const traffic = system.vpn_total_gb ?? "—";
    const connectionState = server.connectionState?.state ||
      server.connection?.state || "unknown";

    const awgClients =
      server.awg?.attributes?.clients || [];

    const xrayClients =
      server.xray?.attributes?.clients || [];

    return `
      <article class="vps">
        <div class="vps-header">
          <div>
            <div class="vps-title">${this._esc(attrs.server_name || `VPS ${index + 1}`)}</div>
            <div class="vps-subtitle">
              ${this._esc(ip)} · ${this._esc(this._mode(mode))}
              · ${this._esc(this._connectionLabel(connectionState))}
            </div>
          </div>
          <div class="actions">
            <button data-action="refresh" data-entity="${this._esc(server.refreshButton?.entity_id || "")}" ${server.refreshButton ? "" : "disabled"}>Обновить</button>
            <button data-action="reconnect" data-entity="${this._esc(server.reconnectButton?.entity_id || "")}" ${server.reconnectButton ? "" : "disabled"}>Переподключить</button>
          </div>
        </div>

        <div class="metrics">
          ${this._metric("CPU", `${cpu}%`)}
          ${this._metric("RAM", `${memory}%`)}
          ${this._metric("HDD", `${diskPercent}%`)}
        </div>

        <div class="info-grid">
          ${this._info(
            "Трафик",
            `${this._number(traffic)} ГБ`
          )}

          ${this._info(
            "Backup",
            this._backupStatus(backup),
            this._backupDetails(backup)
          )}

          ${this._info(
            "Fail2Ban",
            `${fail2ban.currently_banned ?? 0} заблокировано`,
            `Всего: ${fail2ban.total_banned ?? 0}`
          )}
        </div>

        <section class="section">
          <h2>Сервисы</h2>
          ${this._services(services)}
        </section>

        <section class="section">
          <h2>AmneziaWG — клиенты</h2>
          ${this._clients(awgClients)}
        </section>

        <section class="section">
          <h2>Xray — клиенты</h2>
          ${this._clients(xrayClients)}
        </section>
      </article>
    `;
  }

  _metric(title, value) {
    return `
      <div class="metric">
        <div class="label">${title}</div>
        <div class="value">${this._esc(value)}</div>
      </div>
    `;
  }

  _info(title, value, details = "") {
    return `
      <div class="info-card">
        <div class="label">${this._esc(title)}</div>
        <div class="value">${this._esc(value)}</div>
        ${details
          ? `<div class="details">${this._esc(details)}</div>`
          : ""}
      </div>
    `;
  }

  _services(services) {
    const entries = Object.entries(services || {});

    if (!entries.length) {
      return `<div class="muted">Нет данных</div>`;
    }

    return `
      <div class="services-grid">
        ${entries.map(([name, service]) => {
          const running =
            service?.status === 1 ||
            service?.status === true ||
            String(service?.status).toLowerCase() === "active";

          let displayName = name;

          if (name === "stats-http") {
            displayName = "Stats HTTP";
          } else if (name === "zvertbot") {
            displayName = "ZverTBot";
          } else if (name === "fail2ban") {
            displayName = "Fail2Ban";
          } else if (name === "xray") {
            displayName = "Xray";
          } else if (name.startsWith("awg-quick@")) {
            displayName =
              `AmneziaWG ${name.replace("awg-quick@", "")}`;
          }

          return `
            <div class="service-card">
              <div class="service-name">
                ${this._esc(displayName)}
              </div>

              <div class="service-status ${running ? "online" : "offline"}">
                <span class="dot"></span>
                ${running ? "работает" : "остановлен"}
              </div>

              ${
                service?.uptime
                  ? `<div class="uptime">${this._esc(service.uptime)}</div>`
                  : ""
              }
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  _clients(clients) {
    if (!Array.isArray(clients) || !clients.length) {
      return `<div class="muted">Нет подключённых клиентов</div>`;
    }

    return `
      <div class="clients">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Клиент</th>
                <th>IP</th>
                <th>Трафик</th>
                <th>GeoIP</th>
                <th>Статус</th>
                <th>Последний вход</th>
              </tr>
            </thead>
            <tbody>
              ${clients.map(client => this._client(client)).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  _client(client) {
    const online =
      client.online === true ||
      String(client.hs).toLowerCase() === "active";

    const name =
      client.name ||
      client.email ||
      client.username ||
      client.client ||
      "—";

    const ip =
      client.display_ip ||
      client.last_ip ||
      client.ip ||
      client.endpoint ||
      "—";

    const traffic =
      client.total ||
      client.total_bytes ||
      client.traffic ||
      client.total_gb ||
      "—";

    const city =
      client.geoip?.city ||
      client.geo?.city ||
      client.city ||
      "";

    const isp =
      client.geoip?.isp ||
      client.geo?.isp ||
      client.isp ||
      "";

    const emoji =
      client.geoip?.emoji ||
      client.geo?.emoji ||
      "";

    const mobile =
      client.geoip?.mobile ??
      client.geo?.mobile ??
      client.mobile;

    const geo = [
      emoji,
      city,
      isp,
      mobile === true ? "📱" : "",
    ].filter(Boolean).join(" ");

    const lastSeen = online
      ? "Сейчас"
      : this._date(
          client.last_seen ||
          client.lastSeen
        );

    return `
      <tr>
        <td class="client-name">${this._esc(name)}</td>
        <td>${this._esc(ip)}</td>
        <td>${this._esc(this._traffic(traffic))}</td>
        <td>${this._esc(geo || "—")}</td>
        <td>
          <span class="client-status ${online ? "online" : "offline"}">
            <span class="dot"></span>
            ${online ? "online" : "offline"}
          </span>
        </td>
        <td>${this._esc(lastSeen)}</td>
      </tr>
    `;
  }

  _backupStatus(backup) {
    const status =
      String(backup?.status || "").toLowerCase();

    if (status === "success") return "Успешно";
    if (status === "local_only") return "Локальная копия";
    if (status === "failed") return "Ошибка";

    return backup?.status || "Нет данных";
  }

  _backupDetails(backup) {
    const parts = [];

    if (backup?.last_backup) {
      parts.push(this._date(backup.last_backup));
    }

    if (backup?.size_mb != null) {
      parts.push(`${backup.size_mb} МБ`);
    }

    if (backup?.next_run) {
      parts.push(
        `следующий: ${this._date(backup.next_run)}`
      );
    }

    return parts.join(" · ");
  }

  _date(value) {
    if (!value) return "Нет данных";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  _traffic(value) {
    if (value == null || value === "") return "—";
    return String(value);
  }

  _number(value) {
    if (value == null || value === "—") return "—";

    const number = Number(value);

    if (!Number.isFinite(number)) {
      return String(value);
    }

    return number.toLocaleString("ru-RU", {
      maximumFractionDigits: 2,
    });
  }

  _connectionLabel(state) {
    if (state === "connected" || state === "on") return "подключено";
    if (state === "paused") return "пауза после ошибки";
    if (state === "failed" || state === "off") return "ошибка соединения";
    return "состояние неизвестно";
  }

  _mode(mode) {
    if (mode === "tunnel") return "HA Tunnel";
    if (mode === "ssh") return "SSH";
    return mode;
  }

  _esc(value) {
    return String(value ?? "—")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _styles() {
    return `
      <style>
        :host {
          display: block;
          width: 100%;
          color: #e8eaed;
          font-family:
            -apple-system,
            BlinkMacSystemFont,
            "Segoe UI",
            sans-serif;
        }

        * {
          box-sizing: border-box;
        }

        .servers {
          width: 100%;
          display: flex;
          flex-direction: column;
          gap: 24px;
        }

        .vps {
          width: 100%;
          padding: 22px;
          border-radius: 16px;
          background:
            linear-gradient(145deg, #101318, #15191f);
          border: 1px solid rgba(255,255,255,.08);
          box-shadow: 0 10px 30px rgba(0,0,0,.25);
        }

        .vps-header {
          margin-bottom: 20px;
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: flex-start;
        }

        .actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .actions button {
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.06);
          color: inherit;
          border-radius: 9px;
          padding: 8px 12px;
          cursor: pointer;
        }

        .actions button:hover:not(:disabled) {
          background: rgba(56,189,248,.14);
          border-color: rgba(56,189,248,.4);
        }

        .actions button:disabled {
          opacity: .4;
          cursor: not-allowed;
        }

        .vps-title {
          font-size: 25px;
          font-weight: 750;
          letter-spacing: .02em;
          color: #e8f4ff;
        }

        .vps-subtitle {
          margin-top: 6px;
          color: #9ca3af;
          font-size: 14px;
        }

        .metrics,
        .info-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 12px;
        }

        .metrics {
          margin-bottom: 12px;
        }

        .info-grid {
          margin-bottom: 22px;
        }

        .metric,
        .info-card,
        .service-card {
          min-width: 0;
          padding: 14px;
          border-radius: 12px;
          background: rgba(255,255,255,.045);
          border: 1px solid rgba(255,255,255,.07);
        }

        .label {
          color: #9ca3af;
          font-size: 13px;
        }

        .value {
          margin-top: 5px;
          font-size: 20px;
          font-weight: 650;
        }

        .details {
          margin-top: 7px;
          color: #9ca3af;
          font-size: 12px;
          line-height: 1.45;
        }

        .section {
          margin-top: 22px;
        }

        h2 {
          margin: 0 0 10px;
          font-size: 16px;
          font-weight: 650;
        }

        .services-grid {
          display: grid;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          gap: 10px;
        }

        .service-card {
          min-height: 88px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          gap: 8px;
        }

        .service-name {
          font-size: 14px;
          font-weight: 600;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .service-status,
        .client-status {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          font-size: 13px;
        }

        .online {
          color: #72d28c;
        }

        .offline {
          color: #f08080;
        }

        .dot {
          width: 7px;
          height: 7px;
          flex: 0 0 7px;
          border-radius: 50%;
          background: currentColor;
        }

        .uptime {
          color: #8f98a5;
          font-size: 12px;
        }

        .clients {
          overflow: hidden;
          border-radius: 12px;
          background: rgba(255,255,255,.035);
          border: 1px solid rgba(255,255,255,.07);
        }

        .table-wrap {
          width: 100%;
          overflow-x: auto;
        }

        table {
          width: 100%;
          min-width: 760px;
          border-collapse: collapse;
        }

        th,
        td {
          padding: 10px 12px;
          text-align: left;
          border-bottom: 1px solid rgba(255,255,255,.055);
          font-size: 13px;
          white-space: nowrap;
        }

        th {
          color: #8f98a5;
          font-size: 12px;
          font-weight: 600;
        }

        tr:last-child td {
          border-bottom: 0;
        }

        .client-name {
          font-weight: 600;
        }

        .muted,
        .empty {
          padding: 14px;
          color: #8f98a5;
          font-size: 13px;
        }

        @media (max-width: 1000px) {
          .services-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }

        @media (max-width: 700px) {
          .vps {
            padding: 16px;
          }

          .metrics,
          .info-grid,
          .services-grid {
            grid-template-columns: 1fr;
          }
        }


      </style>
    `;
  }
}

if (!customElements.get("zvertbot-vps-panel-v4")) {
  customElements.define("zvertbot-vps-panel-v4", ZverTBotVpsPanelV4);
}
