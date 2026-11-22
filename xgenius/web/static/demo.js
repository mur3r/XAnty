/* Offline preview uses only the remaining profile manager fields. */
'use strict';
const DEMO_STATE = {
  demo: true, phase: 'ready', version: 'demo', base_dir: 'D:\\Profiles',
  summary: { all: 2, browsers: 1, error: 0 }, groups: ['Work'],
  accounts: [
    { index: 1, username: 'profile_one', group: 'Work', proxy: '', status: 'SIGNED IN', status_reason: '', has_browser: true, last_launch: '12:00', need_relogin: false, auto_login: true, login_status: 'signed_in' },
    { index: 2, username: 'profile_two', group: '', proxy: '', status: 'CLOSED', status_reason: '', has_browser: false, last_launch: 'N/A', need_relogin: false, auto_login: false, login_status: 'closed' },
  ],
};
function enterDemo() {
  S.demo = true;
  applyState(DEMO_STATE);
  document.getElementById('demo-banner').classList.remove('hidden');
}
function leaveDemo() {
  S.demo = false;
  S.logs = [];
  rerenderLogs();
  Load.reset();
  document.getElementById('demo-banner').classList.add('hidden');
}
