const {test, beforeEach} = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto} = require('node:crypto');
const auth = require('../auth-service.js');

class MemoryStorage {
  #items = new Map();
  getItem(key) { return this.#items.has(key) ? this.#items.get(key) : null; }
  setItem(key, value) { this.#items.set(key, String(value)); }
  removeItem(key) { this.#items.delete(key); }
}

beforeEach(() => {
  global.crypto = webcrypto;
  global.localStorage = new MemoryStorage();
  global.sessionStorage = new MemoryStorage();
});

test('public demo credentials sign in and restore the demo session', async () => {
  const user = await auth.login('DEMO@vaultai.dev', 'VaultAI@2026');
  assert.equal(user.full_name, 'VaultAI Demo Analyst');
  assert.equal(auth.isAuthenticated(), true);
  assert.equal(auth.getCurrentUser().email, 'demo@vaultai.dev');
});

test('invalid demo credentials are rejected', async () => {
  await assert.rejects(auth.login('demo@vaultai.dev', 'incorrect'), {message: 'INVALID_CREDENTIALS'});
  assert.equal(auth.isAuthenticated(), false);
});

test('signup stores a password digest, signs in, and rejects duplicate email', async () => {
  await auth.signup('Sample Analyst', 'sample@example.com', 'sample pass 123');
  assert.equal(auth.getCurrentUser().full_name, 'Sample Analyst');
  const accounts = JSON.parse(global.localStorage.getItem(auth.storageKeys.accounts));
  assert.equal(accounts.length, 1);
  assert.equal(accounts[0].password, undefined);
  assert.notEqual(accounts[0].password_hash, 'sample pass 123');
  await assert.rejects(auth.signup('Another Name', 'SAMPLE@example.com', 'another pass 456'), {message: 'EMAIL_EXISTS'});
});

test('a new account can sign in after refresh and demo logout clears session markers', async () => {
  await auth.signup('Sample Analyst', 'sample@example.com', 'sample pass 123');
  auth.logout();
  const user = await auth.login('sample@example.com', 'sample pass 123');
  assert.equal(user.email, 'sample@example.com');
  auth.logout();
  assert.equal(auth.isAuthenticated(), false);
});

test('demo session is tab-scoped so a new visit must sign in again', async () => {
  await auth.login('demo@vaultai.dev', 'VaultAI@2026');
  assert.equal(global.localStorage.getItem(auth.storageKeys.session), null);
  assert.ok(global.sessionStorage.getItem(auth.storageKeys.session));
});
