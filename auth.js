/* VaultAI local demo authentication UI; state lives in auth-service.js. */
(() => {
  const shell = document.querySelector('#auth-shell');
  const auth = window.VaultAIDemoAuth;
  document.body.classList.add('auth-mode');
  window.VAULTAI_AUTH_READY = false;
  window.VAULTAI_AUTH_USER = null;

  const icon = '<span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>';
  const path = () => location.pathname.replace(/\/+$/, '') || '/';
  const validEmail = value => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(value) && value.length <= 254;
  const passwordIssue = value => value.length < 8 ? 'Use at least 8 characters.' : '';

  function navigate(destination, {replace = false, welcome = ''} = {}) {
    if (welcome) sessionStorage.setItem('vaultai-demo-welcome', welcome);
    history[replace ? 'replaceState' : 'pushState']({}, '', destination);
    initialize();
  }

  function story() {
    return `<section class="auth-story" aria-label="About VaultAI">
      <a class="auth-brand" href="/login" aria-label="VaultAI sign in">${icon}<span class="auth-brand-copy">vault<span class="brand-ai">ai</span><small>AI-POWERED FINANCIAL INTELLIGENCE</small></span></a>
      <div class="auth-eyebrow">AML RESEARCH · LOCAL DEMO</div>
      <h1>Intelligence<br><em>Without Boundaries.</em></h1>
      <p class="auth-lede">Privacy Without Compromise. Explore a demonstration of collaborative AI for synthetic financial research.</p>
      <div class="auth-visual" role="img" aria-label="Conceptual illustration of three simulated banks sharing model updates">
        <svg viewBox="0 0 600 200" aria-hidden="true">
          <path class="auth-link" d="M108 96 C190 95 220 99 281 99"/><path class="auth-link" d="M300 35 L300 77"/><path class="auth-link" d="M492 96 C408 95 380 99 319 99"/><path class="auth-link center" d="M300 121 L300 161"/>
          <circle class="auth-dot" cx="157" cy="96" r="2.4"/><circle class="auth-dot d2" cx="300" cy="51" r="2.4"/><circle class="auth-dot d3" cx="448" cy="96" r="2.4"/>
          <rect class="auth-node" x="65" y="72" width="43" height="43" rx="14"/><text class="auth-visual-label" x="86" y="98" text-anchor="middle">A</text><rect class="auth-node" x="279" y="11" width="43" height="43" rx="14"/><text class="auth-visual-label" x="300" y="37" text-anchor="middle">B</text><rect class="auth-node" x="492" y="72" width="43" height="43" rx="14"/><text class="auth-visual-label" x="513" y="98" text-anchor="middle">C</text><circle class="auth-node-hub" cx="300" cy="99" r="23"/><text class="auth-visual-label" x="300" y="103" text-anchor="middle">AI</text>
          <text class="auth-visual-label" x="86" y="136" text-anchor="middle">BANK A</text><text class="auth-visual-label" x="300" y="68" text-anchor="middle">BANK B</text><text class="auth-visual-label" x="513" y="136" text-anchor="middle">BANK C</text><text class="auth-visual-label" x="300" y="181" text-anchor="middle">SHARED MODEL UPDATE</text>
        </svg><span class="auth-visual-caption">CONCEPTUAL FEDERATED WORKFLOW</span><span class="auth-visual-note">Synthetic demonstration</span>
      </div>
      <div class="trust-row"><span class="trust-chip">Federated AI</span><span class="trust-chip">Synthetic data</span><span class="trust-chip">Human review</span></div>
      <div class="auth-story-footer">IBM Z DATATHON 2026 · TEAM TECHSHARKS</div>
    </section>`;
  }

  function head(title, description, active = '') {
    return `<div class="auth-card-head"><div class="auth-mini-brand">${icon}<span>vault<span class="brand-ai">ai</span></span></div><span class="auth-secure-label"><i></i>DEMO ACCESS</span></div><h2 id="auth-title">${title}</h2><p class="auth-card-intro">${description}</p>${active ? `<div class="auth-tabs" role="tablist" aria-label="Authentication"><a class="auth-tab ${active === 'login' ? 'active' : ''}" role="tab" aria-selected="${active === 'login'}" href="/login">Sign In</a><a class="auth-tab ${active === 'signup' ? 'active' : ''}" role="tab" aria-selected="${active === 'signup'}" href="/signup">Create account</a></div>` : ''}<div id="auth-message" class="auth-message" role="status" aria-live="polite"></div>`;
  }

  function passwordField(id, label, autocomplete) {
    return `<div class="auth-field"><label for="${id}">${label}</label><div class="auth-input-wrap"><input class="auth-input password" type="password" id="${id}" autocomplete="${autocomplete}" required><button class="password-toggle" type="button" data-toggle-password="${id}" aria-label="Show ${label.toLowerCase()}" aria-pressed="false">SHOW</button></div><div class="field-error" id="${id}-error" aria-live="polite"></div></div>`;
  }

  function loginCard() {
    return `<section class="auth-card" aria-labelledby="auth-title">${head('Welcome back', 'Sign in to your VaultAI demo workspace.', 'login')}<form id="login-form" class="auth-form" novalidate><div class="auth-fields">
      <div class="auth-field"><label for="login-email">Email address</label><input class="auth-input" type="email" id="login-email" autocomplete="email" inputmode="email" placeholder="you@organization.com" required><div class="field-error" id="login-email-error" aria-live="polite"></div></div>
      ${passwordField('login-password', 'Password', 'current-password')}
    </div><div class="auth-options"><span class="auth-session-hint">Sign in is required for each new visit.</span><a class="auth-inline-link" href="/forgot-password">Forgot password?</a></div>
      <button class="button primary auth-submit" type="submit"><span class="spinner" aria-hidden="true"></span><span class="submit-label">Sign In</span></button>
      <div class="auth-demo-box"><strong>Demo account</strong><span>demo@vaultai.dev · VaultAI@2026</span><button type="button" class="auth-inline-link" id="use-demo">Use demo credentials</button></div>
      <div class="auth-bottom">New to VaultAI? <a class="auth-inline-link" href="/signup">Create an account</a></div><div class="auth-security-note">Local demo only · not secure authentication</div></form></section>`;
  }

  function signupCard() {
    return `<section class="auth-card" aria-labelledby="auth-title">${head('Create your account', 'Create a local demo account for this browser.', 'signup')}<form id="signup-form" class="auth-form" novalidate><div class="auth-fields">
      <div class="auth-field"><label for="signup-name">Full name</label><input class="auth-input" type="text" id="signup-name" autocomplete="name" maxlength="100" placeholder="Your name" required><div class="field-error" id="signup-name-error" aria-live="polite"></div></div>
      <div class="auth-field"><label for="signup-email">Email address</label><input class="auth-input" type="email" id="signup-email" autocomplete="email" inputmode="email" maxlength="254" placeholder="you@organization.com" required><div class="field-error" id="signup-email-error" aria-live="polite"></div></div>
      ${passwordField('signup-password', 'Password', 'new-password')}
      <div class="auth-field"><label for="signup-confirm">Confirm password</label><div class="auth-input-wrap"><input class="auth-input password" type="password" id="signup-confirm" autocomplete="new-password" required><button class="password-toggle" type="button" data-toggle-password="signup-confirm" aria-label="Show confirm password" aria-pressed="false">SHOW</button></div><div class="field-error" id="signup-confirm-error" aria-live="polite"></div></div>
      <div><label class="auth-check"><input id="signup-terms" type="checkbox" required><span>I accept the <a href="/legal.html#terms" target="_blank" rel="noopener">demo terms</a> and <a href="/legal.html#privacy" target="_blank" rel="noopener">privacy notice</a>.</span></label><div class="field-error" id="signup-terms-error" aria-live="polite"></div><p class="auth-legal-note">Demo only. Do not enter sensitive or real banking information.</p></div>
    </div><button class="button primary auth-submit" type="submit"><span class="spinner" aria-hidden="true"></span><span class="submit-label">Create Account</span></button><div class="auth-bottom">Already registered? <a class="auth-inline-link" href="/login">Sign in</a></div><div class="auth-security-note">Local demo only · not secure authentication</div></form></section>`;
  }

  function forgotCard() {
    return `<section class="auth-card" aria-labelledby="auth-title">${head('Password recovery', 'This is a demo account. Password recovery by email is not configured.')}<p class="auth-legal-note">Demo accounts are stored in this browser. Create another account or use the public demo credentials on the sign-in page.</p><a class="button primary auth-submit" href="/login" style="display:flex;align-items:center;justify-content:center;text-decoration:none">Return to Sign In</a></section>`;
  }

  function layout(card) { shell.innerHTML = `<div class="auth-layout">${story()}<div class="auth-card-wrap">${card}</div></div>`; }
  function showMessage(text, kind = 'error') {
    const node = document.querySelector('#auth-message'); if (!node) return;
    node.textContent = text; node.className = `auth-message visible${kind === 'error' ? '' : ` ${kind}`}`;
  }
  function setBusy(form, busy, label) {
    const button = form.querySelector('button[type="submit"]'); if (!button) return;
    button.disabled = busy; button.setAttribute('aria-busy', String(busy));
    const text = button.querySelector('.submit-label');
    if (text) { if (!button.dataset.idleLabel) button.dataset.idleLabel = text.textContent; text.textContent = busy ? label : button.dataset.idleLabel; }
  }
  function setError(input, text) {
    input.setAttribute('aria-invalid', text ? 'true' : 'false');
    const node = document.getElementById(`${input.id}-error`); if (node) node.textContent = text;
  }
  function bindToggles() {
    document.querySelectorAll('[data-toggle-password]').forEach(button => button.addEventListener('click', () => {
      const input = document.getElementById(button.dataset.togglePassword), visible = input.type === 'password';
      input.type = visible ? 'text' : 'password'; button.textContent = visible ? 'HIDE' : 'SHOW';
      button.setAttribute('aria-pressed', String(visible)); button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${input.labels?.[0]?.textContent?.toLowerCase() || 'password'}`);
      input.focus({preventScroll: true});
    }));
  }
  function signedIn(user, welcome) {
    window.VAULTAI_AUTH_READY = true; window.VAULTAI_AUTH_USER = user;
    document.body.classList.remove('auth-mode'); shell.replaceChildren();
    if (welcome) sessionStorage.setItem('vaultai-demo-welcome', welcome);
    window.dispatchEvent(new CustomEvent('vaultai-auth-ready', {detail: {user, welcome}}));
  }
  function completeLogin(user, welcome) { signedIn(user, welcome); if (path() !== '/dashboard') navigate('/dashboard'); }

  function showLogin() {
    layout(loginCard()); bindToggles();
    const form = document.querySelector('#login-form'), email = document.querySelector('#login-email'), password = document.querySelector('#login-password');
    email.addEventListener('blur', () => { if (email.value) setError(email, validEmail(email.value.trim()) ? '' : 'Enter a valid email address.'); });
    document.querySelector('#use-demo').addEventListener('click', () => {
      email.value = auth.demoCredentials.email; password.value = auth.demoCredentials.password;
      form.requestSubmit();
    });
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (form.dataset.busy) return;
      const emailError = validEmail(email.value.trim()) ? '' : 'Enter a valid email address.';
      const passwordError = password.value ? '' : 'Enter your password.';
      setError(email, emailError); setError(password, passwordError);
      if (emailError || passwordError) { (emailError ? email : password).focus(); return; }
      form.dataset.busy = 'true'; setBusy(form, true, 'Signing in…');
      try { const user = await auth.login(email.value, password.value); completeLogin(user, `Welcome, ${user.full_name}.`); }
      catch (error) { showMessage(error.message === 'INVALID_CREDENTIALS' ? 'Those demo credentials were not recognized. Check your email and password, or use the demo account above.' : 'Demo sign-in could not be completed in this browser.'); }
      finally { form.dataset.busy = ''; setBusy(form, false, 'Sign In'); }
    });
    email.focus({preventScroll: true});
  }

  function showSignup() {
    layout(signupCard()); bindToggles();
    const form = document.querySelector('#signup-form'), name = document.querySelector('#signup-name'), email = document.querySelector('#signup-email'), password = document.querySelector('#signup-password'), confirm = document.querySelector('#signup-confirm'), terms = document.querySelector('#signup-terms');
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (form.dataset.busy) return;
      let valid = true;
      const nameError = name.value.trim().length < 2 ? 'Enter your full name.' : ''; setError(name, nameError); valid &&= !nameError;
      const emailError = validEmail(email.value.trim()) ? '' : 'Enter a valid email address.'; setError(email, emailError); valid &&= !emailError;
      const pwError = passwordIssue(password.value); setError(password, pwError); valid &&= !pwError;
      const confirmError = confirm.value === password.value ? '' : 'Passwords do not match.'; setError(confirm, confirmError); valid &&= !confirmError;
      const termsError = terms.checked ? '' : 'Accept the demo terms and privacy notice to continue.';
      document.querySelector('#signup-terms-error').textContent = termsError; valid &&= !termsError;
      if (!valid) { form.querySelector('[aria-invalid="true"]')?.focus(); return; }
      form.dataset.busy = 'true'; setBusy(form, true, 'Creating account…');
      try { const user = await auth.signup(name.value.trim(), email.value, password.value); completeLogin(user, `Welcome to VaultAI, ${user.full_name}.`); }
      catch (error) {
        showMessage(error.message === 'EMAIL_EXISTS' ? 'An account with that email already exists. Sign in instead.' : 'This browser could not save the demo account. Try again.');
      } finally { form.dataset.busy = ''; setBusy(form, false, 'Create Account'); }
    });
    email.addEventListener('blur', () => { if (email.value) setError(email, validEmail(email.value.trim()) ? '' : 'Enter a valid email address.'); });
  }

  function showForgot() { layout(forgotCard()); }

  function initialize() {
    const aliases = {'/compare': 'models', '/privacy': 'privacy', '/investigate': 'investigation', '/infrastructure': 'infrastructure'};
    const currentPath = path(), user = auth.getCurrentUser();
    if (aliases[currentPath]) {
      if (!user) { navigate('/login', {replace: true}); return; }
      history.replaceState({}, '', `/dashboard#${aliases[currentPath]}`);
      signedIn(user, ''); return;
    }
    if (currentPath === '/' || currentPath === '/index.html') { navigate('/login', {replace: true}); return; }
    if (currentPath === '/dashboard') {
      if (!user) { navigate('/login', {replace: true}); return; }
      signedIn(user, ''); return;
    }
    window.VAULTAI_AUTH_READY = false; window.VAULTAI_AUTH_USER = null; document.body.classList.add('auth-mode');
    if (currentPath === '/signup') showSignup();
    else if (currentPath === '/forgot-password') showForgot();
    else showLogin();
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (link && ['/login', '/signup', '/forgot-password', '/dashboard'].includes(link.getAttribute('href'))) {
      event.preventDefault(); navigate(link.getAttribute('href'));
    }
    if (event.target.closest('#logout-btn')) { auth.logout(); navigate('/login', {replace: true}); }
  });
  window.addEventListener('popstate', initialize);
  initialize();
})();
