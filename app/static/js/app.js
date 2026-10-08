/* ============================================================
   QC Portal - Frontend JavaScript Logic
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    hideSuseLoader();
    initModals();
    initConnectionTests();
    initQCLiveStream();
    initReportFilters();
});

/* SUSE Chameleon Spinner Loader Controls */
function showSuseLoader(text = 'Running QC Check...') {
    const loader = document.getElementById('suse-loader-overlay');
    if (loader) {
        const subtext = loader.querySelector('.loader-subtext');
        if (subtext) subtext.textContent = text;
        loader.classList.remove('hidden');
    }
}

function hideSuseLoader() {
    const loader = document.getElementById('suse-loader-overlay');
    if (loader) {
        setTimeout(() => {
            loader.classList.add('hidden');
        }, 300);
    }
}

/* Modals */
function initModals() {
    document.querySelectorAll('[data-modal-target]').forEach(btn => {
        btn.addEventListener('click', () => {
            const modalId = btn.getAttribute('data-modal-target');
            const modal = document.getElementById(modalId);
            if (modal) modal.classList.add('active');
        });
    });

    document.querySelectorAll('.modal-close, [data-modal-close]').forEach(btn => {
        btn.addEventListener('click', () => {
            const modal = btn.closest('.modal');
            if (modal) modal.classList.remove('active');
        });
    });

    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) {
            e.target.classList.remove('active');
        }
    });
}

/* SSH Connection Testing */
function initConnectionTests() {
    document.querySelectorAll('.btn-test-conn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const hostId = btn.getAttribute('data-host-id');
            const origHTML = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Testing...';

            try {
                const res = await fetch(`/api/hosts/test-connection/${hostId}`, { method: 'POST' });
                const data = await res.json();
                
                if (data.success) {
                    alert('✅ ' + data.message);
                } else {
                    alert('❌ Connection Failed:\n' + data.message);
                }
            } catch (err) {
                alert('❌ Error testing connection: ' + err.message);
            } finally {
                btn.disabled = false;
                btn.innerHTML = origHTML;
            }
        });
    });
}

/* Fetch iLO User List into Dropdown */
async function fetchIloUsers(hostId) {
    const selectElem = document.getElementById(`ilo-user-select-${hostId}`);
    if (!selectElem) return;

    selectElem.innerHTML = '<option value="">Loading iLO users via SSH...</option>';

    try {
        const res = await fetch(`/api/hosts/ilo-users/${hostId}`);
        const data = await res.json();

        if (data.success && data.users && data.users.length > 0) {
            selectElem.innerHTML = '';
            data.users.forEach(u => {
                const opt = document.createElement('option');
                opt.value = u.id;
                opt.textContent = `ID ${u.id}: ${u.name} (${u.priv})`;
                if (u.name.toLowerCase() === 'root' || u.id === '2') opt.selected = true;
                selectElem.appendChild(opt);
            });
        } else {
            selectElem.innerHTML = '<option value="2">ID 2: Default Root/Admin</option>';
            if (data.message) {
                alert('Notice fetching iLO users: ' + data.message);
            }
        }
    } catch (err) {
        selectElem.innerHTML = '<option value="2">ID 2: Default Root/Admin</option>';
    }
}

/* Ad-Hoc Command Console execution */
async function runAdhocCommand() {
    const hostSelect = document.getElementById('adhoc-host-id');
    const cmdInput = document.getElementById('adhoc-cmd-input');
    const outBox = document.getElementById('adhoc-output-box');

    const hostId = hostSelect ? hostSelect.value : null;
    const command = cmdInput ? cmdInput.value.strip ? cmdInput.value.strip() : cmdInput.value.trim() : '';

    if (!hostId || !command) {
        alert('Please select a host and enter a command (e.g. uptime)');
        return;
    }

    outBox.style.display = 'block';
    outBox.textContent = `> Running '${command}' via SSH...\n`;

    try {
        const res = await fetch('/api/adhoc-command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ host_id: hostId, command: command })
        });
        const data = await res.json();

        if (data.success) {
            outBox.textContent = `$ ${command}\n\n${data.output}`;
        } else {
            outBox.textContent = `$ ${command}\n[Exit Code ${data.exit_code}]\n\n${data.output}`;
        }
    } catch (err) {
        outBox.textContent = `Error executing command: ${err.message}`;
    }
}

/* SSE QC Execution Live Streaming */
function initQCLiveStream() {
    const terminal = document.getElementById('terminal-body');
    const hostId = terminal ? terminal.getAttribute('data-host-id') : null;

    if (!terminal || !hostId) return;

    showSuseLoader('Connecting to Host Node...');

    const eventSource = new EventSource(`/api/stream-qc/${hostId}`);

    eventSource.onmessage = (e) => {
        hideSuseLoader();
        const text = e.data;
        const line = document.createElement('div');
        line.className = 'log-line';

        if (text.includes('[PASS]')) line.classList.add('pass');
        else if (text.includes('[FAIL]')) line.classList.add('fail');
        else if (text.includes('[WARNING]') || text.includes('[WARN]')) line.classList.add('warn');
        else if (text.includes('====') || text.includes('Running')) line.classList.add('banner');
        else line.classList.add('info');

        line.textContent = text;
        terminal.appendChild(line);
        terminal.scrollTop = terminal.scrollHeight;

        if (text.includes('[COMPLETE]') || text.includes('[FAIL] Failed to upload') || text.includes('[SUCCESS]')) {
            eventSource.close();
            const statusInd = document.getElementById('qc-status-indicator');
            if (statusInd) {
                statusInd.innerHTML = '<span class="status-badge PASS"><i class="fa-solid fa-circle-check"></i> Finished</span>';
            }
            
            const reportBtn = document.getElementById('btn-view-report');
            if (reportBtn) {
                reportBtn.style.display = 'inline-flex';
            }
        }
    };

    eventSource.onerror = (err) => {
        hideSuseLoader();
        eventSource.close();
    };
}

/* Report Table Filter buttons */
function initReportFilters() {
    const filterBtns = document.querySelectorAll('.filter-btn');
    const tableRows = document.querySelectorAll('#report-table-body tr');

    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const filter = btn.getAttribute('data-filter');

            tableRows.forEach(row => {
                const status = row.getAttribute('data-status');
                const section = row.getAttribute('data-section');

                if (filter === 'all') {
                    row.style.display = '';
                } else if (filter === status) {
                    row.style.display = '';
                } else if (filter === section) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    });
}

/* Remediation Trigger helper */
async function runRemediation(hostId, action, payload = {}) {
    if (!confirm(`Are you sure you want to execute write remediation (${action}) on host?`)) {
        return;
    }

    showSuseLoader(`Executing Remediation (${action})...`);

    try {
        const res = await fetch(`/api/remediate/${hostId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, ...payload })
        });
        const data = await res.json();
        hideSuseLoader();

        if (data.success) {
            alert('✅ Remediation Completed:\n' + data.details);
        } else {
            alert('❌ Remediation Failed:\n' + (data.details || data.message));
        }
    } catch (err) {
        hideSuseLoader();
        alert('❌ Error: ' + err.message);
    }
}
