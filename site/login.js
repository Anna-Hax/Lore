import { hosted, loggedIn, login } from './mcp-client.js?v=12';

const action = document.getElementById('loginAction');
const description = document.getElementById('loginDescription');
const message = text => {
  action.querySelector('[role="alert"]')?.remove();
  const node = document.createElement('p'); node.className = 'error'; node.setAttribute('role', 'alert'); node.textContent = text;
  action.append(node);
};
if (hosted()) {
  if (loggedIn()) {
    description.textContent = 'Your Lore session is active. Continue to your account and wallets.';
    const link = document.createElement('a'); link.className = 'button primary'; link.href = 'workspace.html#account'; link.textContent = 'Open your workspace →'; action.append(link);
  } else {
    const button = document.createElement('button'); button.className = 'primary'; button.type = 'button'; button.textContent = 'Continue with World ID →';
    button.onclick = async () => { button.disabled = true; try { await login(); } catch (e) { message(e.message || String(e)); button.disabled = false; } };
    action.append(button);
  }
} else {
  description.textContent = 'Open this page on your Lore gateway to verify with World ID. The local preview cannot verify an identity.';
  const form = document.createElement('form'); form.className = 'gateway-form';
  const label = document.createElement('label'); label.htmlFor = 'gatewayUrl'; label.textContent = 'Lore gateway address';
  const input = document.createElement('input'); input.id = 'gatewayUrl'; input.type = 'url'; input.required = true;
  input.placeholder = 'https://your-lore-gateway.example'; input.value = 'http://127.0.0.1:8080';
  const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = 'The default is a gateway running on this computer.';
  const button = document.createElement('button'); button.className = 'primary'; button.textContent = 'Open gateway sign-in →';
  form.append(label, input, hint, button); action.append(form);
  form.onsubmit = e => {
    e.preventDefault();
    try {
      const url = new URL(input.value);
      if (url.username || url.password || (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '::1'].includes(url.hostname)))) throw new Error('Use HTTPS, or HTTP for a gateway on localhost.');
      url.pathname = '/app/login.html'; url.search = ''; url.hash = location.hash;
      location.assign(url.href);
    } catch (err) { message(err.message || String(err)); }
  };
}
