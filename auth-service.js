/* Local-only demo authentication. Never use this module for real accounts. */
(function (root, factory) {
  const service = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = service;
  if (root) root.VaultAIDemoAuth = service;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const ACCOUNT_KEY = 'vaultai-demo-accounts';
  const SESSION_KEY = 'vaultai-demo-session';
  const DEMO_EMAIL = 'demo@vaultai.dev';
  const DEMO_PASSWORD = 'VaultAI@2026';
  const normalizeEmail = email => String(email || '').trim().toLowerCase();
  const store = () => globalThis.localStorage;
  const sessionStore = () => globalThis.sessionStorage;

  async function passwordHash(password) {
    if (!globalThis.crypto?.subtle) throw new Error('DEMO_STORAGE_UNAVAILABLE');
    const bytes = new TextEncoder().encode(password);
    const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function accounts() {
    try {
      const value = JSON.parse(store().getItem(ACCOUNT_KEY) || '[]');
      return Array.isArray(value) ? value : [];
    } catch (_) { return []; }
  }

  function persistSession(user) {
    logout();
    sessionStore().setItem(SESSION_KEY, JSON.stringify({email: user.email, full_name: user.full_name}));
  }

  function getCurrentUser() {
    for (const storage of [store(), sessionStore()]) {
      try {
        const user = JSON.parse(storage.getItem(SESSION_KEY) || 'null');
        if (user && typeof user.email === 'string') return user;
      } catch (_) { storage.removeItem(SESSION_KEY); }
    }
    return null;
  }

  function logout() {
    store().removeItem(SESSION_KEY);
    sessionStore().removeItem(SESSION_KEY);
  }

  async function login(email, password) {
    const normalized = normalizeEmail(email);
    let user;
    if (normalized === DEMO_EMAIL && password === DEMO_PASSWORD) {
      user = {email: DEMO_EMAIL, full_name: 'VaultAI Demo Analyst'};
    } else {
      const record = accounts().find(account => account.email === normalized);
      if (!record || record.password_hash !== await passwordHash(password)) throw new Error('INVALID_CREDENTIALS');
      user = {email: record.email, full_name: record.full_name};
    }
    persistSession(user);
    return user;
  }

  async function signup(name, email, password) {
    const normalized = normalizeEmail(email);
    if (normalized === DEMO_EMAIL || accounts().some(account => account.email === normalized)) {
      throw new Error('EMAIL_EXISTS');
    }
    const record = {email: normalized, full_name: String(name).trim(), password_hash: await passwordHash(password)};
    const allAccounts = accounts();
    allAccounts.push(record);
    store().setItem(ACCOUNT_KEY, JSON.stringify(allAccounts));
    const user = {email: record.email, full_name: record.full_name};
    persistSession(user);
    return user;
  }

  return {
    login, signup, logout, getCurrentUser,
    isAuthenticated: () => Boolean(getCurrentUser()),
    demoCredentials: Object.freeze({email: DEMO_EMAIL, password: DEMO_PASSWORD}),
    storageKeys: Object.freeze({accounts: ACCOUNT_KEY, session: SESSION_KEY}),
  };
});
