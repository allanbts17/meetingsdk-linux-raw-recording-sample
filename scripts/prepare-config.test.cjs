const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');

test('native JWT signature, expiry, disabled media and no secret output', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zoom-config-test-'));
  const input = path.join(dir, 'input.json');
  const output = path.join(dir, 'config.txt');
  const env = {...process.env};
  delete env.ZOOM_CLIENT_ID;
  delete env.ZOOM_CLIENT_SECRET;
  const run = (...args) => spawnSync(process.execPath, [path.join(__dirname, 'prepare-config.cjs'), input, output, ...args], {env, encoding: 'utf8'});
  fs.writeFileSync(input, JSON.stringify({clientId: 'test-client', clientSecret: 'test-secret', meetingNumber: '12345678901', meetingPassword: 'test-pass', participantName: 'TestBot'}));
  try {
    const result = run();
    assert.equal(result.status, 0, result.stderr);
    const config = fs.readFileSync(output, 'utf8');
    const jwt = config.match(/^token: "(.+)"$/m)[1];
    const [header, payload, signature] = jwt.split('.');
    assert.equal(signature, crypto.createHmac('sha256', 'test-secret').update(`${header}.${payload}`).digest('base64url'));
    const claims = JSON.parse(Buffer.from(payload, 'base64url'));
    assert.equal(claims.appKey, 'test-client');
    assert.equal(claims.exp - claims.iat, 7200);
    assert.equal(claims.tokenExp, claims.exp);
    assert.ok(Math.abs(claims.iat - Math.floor(Date.now() / 1000)) <= 35);
    for (const key of ['GetVideoRawData', 'GetAudioRawData', 'SendVideoRawData', 'SendAudioRawData']) assert.ok(config.includes(`${key}: "false"`));
    for (const secret of [jwt, 'test-secret', 'test-pass']) assert.ok(!(result.stdout + result.stderr).includes(secret));
    assert.equal(run('--av').status, 0);
    const avConfig = fs.readFileSync(output, 'utf8');
    assert.ok(avConfig.includes('SendVideoRawData: "true"'));
    assert.ok(avConfig.includes('SendAudioRawData: "true"'));
    assert.ok(avConfig.includes('GetAudioRawData: "false"'));
    fs.writeFileSync(input, '{"clientSecret":"SENSITIVE", invalid}');
    const invalid = run();
    assert.equal(invalid.status, 1);
    assert.ok(!invalid.stderr.includes('SENSITIVE'));
    assert.equal(fs.readFileSync(output, 'utf8'), avConfig);
  } finally {
    fs.unlinkSync(input);
    if (fs.existsSync(output)) fs.unlinkSync(output);
    fs.rmdirSync(dir);
  }
});
