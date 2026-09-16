class ZverTBotVpsPanelV3 extends HTMLElement {
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
        (
          entityId.includes("zvertbot_vps_all_stats") ||
          state.attributes?.friendly_name?.toLowerCase().includes("vps all stats")
        )
    );

    const servers = allStats.map(([entityId, state]) => {
      const attrs = state.attributes || {};

      return {
        entityId,
        attrs,
        allStats: state,
        awg: this._findClientSensor(states, "awg"),
        xray: this._findClientSensor(states, "xray"),
      };
    });

    this._servers = servers;
    this._render();
  }

  _findClientSensor(states, type) {
    const entries = Object.entries(states);

    return entries.find(([entityId, state]) => {
      const id = entityId.toLowerCase();
      const name = String(
        state.attributes?.friendly_name || ""
      ).toLowerCase();

      if (!id.startsWith("sensor.")) return false;

      if (type === "awg") {
        return (
          id.includes("zvertbot_vps_awg_clients") ||
          name.includes("vps awg clients")
        );
      }

      return (
        id.includes("zvertbot_vps_xray_clients") ||
        name.includes("vps xray clients")
      );
    })?.[1] || null;
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

    const awgClients =
      server.awg?.attributes?.clients || [];

    const xrayClients =
      server.xray?.attributes?.clients || [];

    return `
      <article class="vps">
        <div class="vps-header">
          <div>
            <div class="vps-title">VPS ${index + 1}</div>
            <div class="vps-subtitle">
              ${this._esc(ip)} · ${this._esc(this._mode(mode))}
            </div>
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
        }

        .vps-title {
          font-size: 25px;
          font-weight: 700;
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

/* V3 — Cyber Control */
:host {
  --vps-bg: #080b10;
  --vps-card: #0d1219;
  --vps-card2: #111821;
  --vps-border: #1d2a38;
  --vps-text: #e8f0f7;
  --vps-muted: #7f93a5;
  --vps-blue: #38bdf8;
  --vps-green: #34d399;
  --vps-red: #fb7185;
}

.vps-panel {
  background: linear-gradient(145deg, #080b10 0%, #0c1219 55%, #071017 100%);
  color: var(--vps-text);
  border: 1px solid #172532;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025), 0 18px 50px rgba(0,0,0,.28);
}

.vps-title {
  letter-spacing: .08em;
  text-transform: uppercase;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.vps-server {
  background: linear-gradient(160deg, rgba(13,18,25,.98), rgba(8,13,19,.98));
  border: 1px solid var(--vps-border);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.025);
}

.vps-metric {
  background: #0a1016;
  border: 1px solid #1a2835;
}

.vps-metric-value {
  color: var(--vps-blue);
  text-shadow: 0 0 14px rgba(56,189,248,.25);
}

.vps-section-title {
  color: #b8c8d6;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.vps-service {
  background: #0a1016;
  border: 1px solid #1a2835;
}

.vps-online {
  color: var(--vps-green) !important;
}

.vps-offline {
  color: var(--vps-red) !important;
}

.vps-table {
  background: #090e14;
  border: 1px solid #182633;
}

.vps-table th {
  background: #0e1720;
  color: #8da5b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  text-transform: uppercase;
  letter-spacing: .04em;
}

.vps-table td {
  border-color: #172532;
}

.vps-table tr:hover td {
  background: #0d1720;
}

      </style>
    `;
  }
}

if (!customElements.get("zvertbot-vps-panel-v3")) {
  customElements.define("zvertbot-vps-panel-v3", ZverTBotVpsPanelV3);
}
