const {test} = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {createRequire} = require('node:module');
const backend = process.env.ZOOM_TEST_BACKEND_DIR;
if (!backend) throw new Error('Set ZOOM_TEST_BACKEND_DIR to the compiled backend');
const requireBackend = createRequire(path.join(backend, 'package.json'));
const {authorizeZoomBot} = requireBackend('./lib/routes/zoomBot.js');
const {zoomBotRequest, ZoomBotError} = requireBackend('./lib/services/zoomBotService.js');
const {GoogleAuth} = requireBackend('google-auth-library');

test('authorization fails closed and permits only verified allowlisted UID', async () => {
  const old = process.env.ZOOM_BOT_ALLOWED_UIDS;
  try {
    async function invoke(config, header, verify) {
      process.env.ZOOM_BOT_ALLOWED_UIDS = config;
      const result = {next: false};
      const res = {setHeader() {}, status(code) {result.status = code; return this;},
        json(body) {result.body = body; return this;}};
      await authorizeZoomBot(verify)({get: () => header}, res, () => {result.next = true;});
      return result;
    }
    assert.equal((await invoke('', 'Bearer private-token', async () => ({uid: 'allowed'}))).status, 503);
    assert.equal((await invoke('allowed', '', async () => {throw Error('not called');})).status, 401);
    const invalid = await invoke('allowed', 'Bearer private-token', async () => {throw Error('private-value');});
    assert.equal(invalid.status, 401);
    assert.ok(!JSON.stringify(invalid).includes('private-value'));
    assert.equal((await invoke('allowed', 'Bearer token', async () => ({uid: 'other'}))).status, 403);
    assert.equal((await invoke(' allowed, second ', 'Bearer token', async () => ({uid: 'allowed'}))).next, true);
  } finally {
    if (old === undefined) delete process.env.ZOOM_BOT_ALLOWED_UIDS;
    else process.env.ZOOM_BOT_ALLOWED_UIDS = old;
  }
});

test('IAM audience, stable key, no automatic retries and sanitized errors', async () => {
  const original = GoogleAuth.prototype.getIdTokenClient;
  let calls = 0;
  let request;
  GoogleAuth.prototype.getIdTokenClient = async function(audience) {
    assert.equal(audience, 'https://zoom-bot-api-722146628233.us-central1.run.app');
    return {request: async (options) => {
      calls++;
      request = options;
      return {status: 202, data: {operation_id: 'operation'}};
    }};
  };
  try {
    const key = 'stable-idempotency-key';
    await zoomBotRequest('POST', '/v1/bots', {meeting: {}}, key);
    assert.equal(request.headers['Idempotency-Key'], key);
    assert.equal(request.retry, false);
    assert.equal(request.maxRedirects, 0);
    await assert.rejects(() => zoomBotRequest('POST', '/v1/bots', {}, 'short'), ZoomBotError);
    assert.equal(calls, 1);
    GoogleAuth.prototype.getIdTokenClient = async () => ({request: async () => {
      calls++;
      throw {message: 'private-token', config: {data: 'private-password'},
        response: {status: 409, data: {error: {code: 'CAPACITY_EXCEEDED'}}}};
    }});
    await assert.rejects(() => zoomBotRequest('POST', '/v1/bots', {}, key),
      (error) => error.status === 409 && error.code === 'CAPACITY_EXCEEDED' &&
        !JSON.stringify(error).includes('private-password'));
    assert.equal(calls, 2);
  } finally {
    GoogleAuth.prototype.getIdTokenClient = original;
  }
});
