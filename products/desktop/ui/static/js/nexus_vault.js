/* nexus_vault.js */

const api = {
    async get(url) {
        const r = await fetch(url);
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        return d;
    },
    async post(url, body) {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        return d;
    },
    async del(url) {
        const r = await fetch(url, { method: 'DELETE' });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        return d;
    },
    async put(url, body) {
        const r = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
        return d;
    },
};

function esc(v) {
    return String(v ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Toast ────────────────────────────────────────────────────────────────────

let _toastTimer = null;

function toast(msg, type = 'info') {
    const el = document.getElementById('vaultToast');
    el.textContent = msg;
    el.className = `vault-toast toast-${type}`;
    el.style.display = 'block';
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { el.style.display = 'none'; }, 3500);
}

// ── Estado del vault ─────────────────────────────────────────────────────────

let _credStubs = {};   // device_id → stub

async function checkVaultStatus() {
    try {
        const s = await api.get('/api/nexus/vault/status');
        if (!s.initialized) {
            showSetupScreen();
        } else if (s.locked) {
            showLockScreen();
        } else {
            showVaultMain();
        }
    } catch (e) {
        showLockScreen();
    }
}

function showLockScreen() {
    document.getElementById('vaultLockScreen').style.display = 'flex';
    document.getElementById('vaultMain').style.display = 'none';
    document.getElementById('vaultLockTitle').textContent = 'Vault bloqueado';
    document.getElementById('vaultLockDesc').textContent = 'Introduce la contraseña maestra para acceder a las credenciales.';
    document.getElementById('vaultUnlockBtn').textContent = 'Desbloquear';
    document.getElementById('vaultLockIcon').textContent = '🔒';
}

function showSetupScreen() {
    document.getElementById('vaultLockScreen').style.display = 'flex';
    document.getElementById('vaultMain').style.display = 'none';
    document.getElementById('vaultLockTitle').textContent = 'Primera configuración';
    document.getElementById('vaultLockDesc').textContent = 'El vault no está inicializado. Establece una contraseña maestra para cifrar las credenciales.';
    document.getElementById('vaultUnlockBtn').textContent = 'Inicializar vault';
    document.getElementById('vaultLockIcon').textContent = '🔐';
}

async function showVaultMain() {
    document.getElementById('vaultLockScreen').style.display = 'none';
    document.getElementById('vaultMain').style.display = 'flex';
    await Promise.all([loadDevices(), loadCredStubs()]);
}

// ── Unlock / Setup ────────────────────────────────────────────────────────────

document.getElementById('vaultUnlockForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pw = document.getElementById('masterPasswordInput').value;
    const errEl = document.getElementById('vaultUnlockError');
    const btn = document.getElementById('vaultUnlockBtn');
    errEl.style.display = 'none';
    btn.disabled = true;
    btn.textContent = '...';

    try {
        const status = await api.get('/api/nexus/vault/status');
        if (!status.initialized) {
            await api.post('/api/nexus/vault/setup', { master_password: pw });
            toast('Vault inicializado', 'ok');
        } else {
            await api.post('/api/nexus/vault/unlock', { master_password: pw });
            toast('Vault desbloqueado', 'ok');
        }
        document.getElementById('masterPasswordInput').value = '';
        showVaultMain();
    } catch (err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Desbloquear';
    }
});

async function lockVault() {
    try {
        await api.post('/api/nexus/vault/lock', {});
        toast('Vault bloqueado', 'info');
        showLockScreen();
    } catch (e) {
        toast(e.message, 'err');
    }
}

// ── CMDB Devices ─────────────────────────────────────────────────────────────

let _devices = [];

async function loadDevices() {
    try {
        const d = await api.get('/api/nexus/cmdb/devices?enabled_only=false');
        _devices = d.devices || [];
        renderDevicesTable();
        document.getElementById('deviceCount').textContent = `${_devices.length} dispositivo${_devices.length !== 1 ? 's' : ''}`;
    } catch (e) {
        toast('Error cargando dispositivos: ' + e.message, 'err');
    }
}

async function loadCredStubs() {
    try {
        const d = await api.get('/api/nexus/vault/credentials');
        _credStubs = {};
        (d.credentials || []).forEach(c => { _credStubs[c.device_id] = c; });
        renderDevicesTable();
    } catch (e) {
        // vault bloqueado o sin credenciales — ok
    }
}

function renderDevicesTable() {
    const tbody = document.getElementById('devicesBody');
    if (!_devices.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="vault-empty">Sin dispositivos. Añade el primero.</td></tr>';
        return;
    }

    tbody.innerHTML = _devices.map(d => {
        const cred = _credStubs[d.device_id];
        const credBadge = cred
            ? `<span class="vault-badge vault-badge-green">${esc(cred.auth_method)} · ${esc(cred.username)}</span>`
            : `<span class="vault-badge vault-badge-red">Sin credencial</span>`;

        const typeBadge = `<span class="vault-badge vault-badge-gray">${esc(d.type)}</span>`;
        const protoBadge = `<span class="vault-badge vault-badge-gray">${esc(d.management_protocol)}</span>`;

        return `
        <tr>
            <td><strong>${esc(d.name)}</strong>${d.notes ? `<br><span style="font-size:11px;color:#666">${esc(d.notes.substring(0,60))}</span>` : ''}</td>
            <td><code style="font-size:12px">${esc(d.ip)}${d.port !== 22 ? ':' + d.port : ''}</code></td>
            <td>${typeBadge}</td>
            <td>${protoBadge}</td>
            <td>${esc(d.os || '—')}</td>
            <td>${credBadge}</td>
            <td>
                <div class="vault-row-actions">
                    <button class="btn-icon" onclick="openCredModal('${esc(d.device_id)}','${esc(d.name)}')" title="Credenciales">🔑</button>
                    <button class="btn-icon" onclick="testConnection('${esc(d.device_id)}', this)" title="Probar conexión">⚡</button>
                    <button class="btn-icon" onclick="openDeviceModal('${esc(d.device_id)}')" title="Editar">✏️</button>
                    <button class="btn-icon" onclick="deleteDevice('${esc(d.device_id)}','${esc(d.name)}')" title="Eliminar" style="color:#e8231a">✕</button>
                </div>
            </td>
        </tr>`;
    }).join('');
}

// ── Device modal ──────────────────────────────────────────────────────────────

function openDeviceModal(deviceId) {
    const modal = document.getElementById('deviceModal');
    const form  = document.getElementById('deviceForm');
    form.reset();

    if (deviceId) {
        const d = _devices.find(x => x.device_id === deviceId);
        if (!d) return;
        document.getElementById('deviceModalTitle').textContent = 'Editar dispositivo';
        document.getElementById('deviceId').value    = d.device_id;
        document.getElementById('dName').value       = d.name;
        document.getElementById('dIp').value         = d.ip;
        document.getElementById('dPort').value       = d.port;
        document.getElementById('dType').value       = d.type;
        document.getElementById('dProtocol').value   = d.management_protocol;
        document.getElementById('dOs').value         = d.os || '';
        document.getElementById('dVendor').value     = d.vendor || '';
        document.getElementById('dFqdn').value       = d.fqdn || '';
        document.getElementById('dNotes').value      = d.notes || '';
    } else {
        document.getElementById('deviceModalTitle').textContent = 'Añadir dispositivo';
        document.getElementById('deviceId').value = '';
    }
    modal.style.display = 'flex';
}

document.getElementById('deviceForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('deviceSaveBtn');
    btn.disabled = true;
    const deviceId = document.getElementById('deviceId').value;
    const body = {
        name:                document.getElementById('dName').value,
        ip:                  document.getElementById('dIp').value,
        port:                parseInt(document.getElementById('dPort').value) || 22,
        type:                document.getElementById('dType').value,
        management_protocol: document.getElementById('dProtocol').value,
        os:                  document.getElementById('dOs').value,
        vendor:              document.getElementById('dVendor').value,
        fqdn:                document.getElementById('dFqdn').value || null,
        notes:               document.getElementById('dNotes').value,
    };

    try {
        if (deviceId) {
            await api.put(`/api/nexus/cmdb/devices/${deviceId}`, body);
            toast('Dispositivo actualizado', 'ok');
        } else {
            await api.post('/api/nexus/cmdb/devices', body);
            toast('Dispositivo añadido', 'ok');
        }
        closeModal('deviceModal');
        await loadDevices();
    } catch (err) {
        toast(err.message, 'err');
    } finally {
        btn.disabled = false;
    }
});

async function deleteDevice(deviceId, name) {
    if (!confirm(`¿Eliminar "${name}" del inventario?`)) return;
    try {
        await api.del(`/api/nexus/cmdb/devices/${deviceId}`);
        toast(`${name} eliminado`, 'info');
        await loadDevices();
    } catch (e) {
        toast(e.message, 'err');
    }
}

// ── Credential modal ──────────────────────────────────────────────────────────

function openCredModal(deviceId, deviceName) {
    document.getElementById('credDeviceId').value      = deviceId;
    document.getElementById('credModalDeviceName').textContent = deviceName;
    document.getElementById('credForm').reset();
    toggleSshKey();
    document.getElementById('credModal').style.display = 'flex';
}

document.getElementById('credForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const deviceId   = document.getElementById('credDeviceId').value;
    const authMethod = document.getElementById('credAuthMethod').value;
    const username   = document.getElementById('credUsername').value;
    const secret     = document.getElementById('credSecret').value;
    const sshKey     = document.getElementById('credSshKey').value || null;

    try {
        await api.post(`/api/nexus/vault/credentials/${deviceId}`, {
            auth_method: authMethod,
            username,
            secret,
            ssh_key: sshKey,
        });
        toast('Credencial guardada (cifrada)', 'ok');
        closeModal('credModal');
        await loadCredStubs();
    } catch (err) {
        toast(err.message, 'err');
    }
});

function toggleSshKey() {
    const method    = document.getElementById('credAuthMethod').value;
    const sshBlock  = document.getElementById('sshKeyField');
    const secBlock  = document.getElementById('secretField');
    const secLabel  = document.getElementById('secretLabel');

    if (method === 'ssh_key') {
        sshBlock.style.display  = 'block';
        secLabel.textContent    = 'Passphrase (opcional)';
    } else {
        sshBlock.style.display  = 'none';
        secLabel.textContent    = method === 'api_token' ? 'API Token *' : 'Password *';
    }
}

function toggleSecretVisibility() {
    const input = document.getElementById('credSecret');
    input.type  = input.type === 'password' ? 'text' : 'password';
}

function loadSshKeyFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => { document.getElementById('credSshKey').value = e.target.result; };
    reader.readAsText(file);
}

// ── Test connection ───────────────────────────────────────────────────────────

async function testConnection(deviceId, btn) {
    const orig = btn.textContent;
    btn.textContent = '…';
    btn.disabled = true;
    try {
        const r = await api.post(`/api/nexus/vault/test/${deviceId}`, {});
        toast(r.ok ? `✓ ${r.message}` : `✗ ${r.message}`, r.ok ? 'ok' : 'err');
    } catch (e) {
        toast('Error: ' + e.message, 'err');
    } finally {
        btn.textContent = orig;
        btn.disabled = false;
    }
}

// ── Modal helpers ──────────────────────────────────────────────────────────────

function closeModal(id) {
    document.getElementById(id).style.display = 'none';
}

function closeOnOverlay(event, id) {
    if (event.target === document.getElementById(id)) closeModal(id);
}

// ── Init ──────────────────────────────────────────────────────────────────────

checkVaultStatus();
