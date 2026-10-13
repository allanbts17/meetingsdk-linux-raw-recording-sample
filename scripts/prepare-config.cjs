const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const root = path.resolve(__dirname, '..');
const positional = process.argv.slice(2).filter(arg => arg !== '--video' && arg !== '--av');
const input = path.resolve(positional[0] || path.join(root, 'config/local.json'));
const output = path.resolve(positional[1] || path.join(root, 'demo/config.txt'));

try {
  const settings = JSON.parse(fs.readFileSync(input, 'utf8').replace(/^\uFEFF/, ''));
  const clientId = process.env.ZOOM_CLIENT_ID || settings.clientId;
  const clientSecret = process.env.ZOOM_CLIENT_SECRET || settings.clientSecret;
  for (const [key, value] of Object.entries({clientId, clientSecret, meetingNumber: settings.meetingNumber, participantName: settings.participantName})) {
    if (typeof value !== 'string' || !value.trim()) throw new Error(`Missing field: ${key}`);
  }
  if (!/^\d{9,11}$/.test(settings.meetingNumber) || /^0+$/.test(settings.meetingNumber)) {
    throw new Error('meetingNumber must contain 9-11 digits without spaces.');
  }
  for (const key of ['meetingPassword', 'participantName']) {
    if (typeof settings[key] !== 'string' || /["\r\n]/.test(settings[key])) {
      throw new Error(`Invalid field: ${key}; use text without quotes or line breaks.`);
    }
  }
  const issuedAt = Math.floor(Date.now() / 1000) - 30;
  const expiresAt = issuedAt + 7200;
  const encode = value => Buffer.from(JSON.stringify(value)).toString('base64url');
  const unsigned = `${encode({alg: 'HS256', typ: 'JWT'})}.${encode({appKey: clientId, iat: issuedAt, exp: expiresAt, tokenExp: expiresAt})}`;
  const signature = crypto.createHmac('sha256', clientSecret).update(unsigned).digest('base64url');
  const fields = {
    meeting_number: settings.meetingNumber,
    participant_name: settings.participantName,
    token: `${unsigned}.${signature}`,
    meeting_password: settings.meetingPassword,
    recording_token: '', onBehalfOf_Token: '',
    GetVideoRawData: 'false', GetAudioRawData: 'false',
    SendVideoRawData: process.argv.includes('--video') || process.argv.includes('--av') ? 'true' : 'false',
    SendAudioRawData: process.argv.includes('--av') ? 'true' : 'false',
    video_source: '/app/media/video.mp4'
  };
  fs.mkdirSync(path.dirname(output), {recursive: true});
  fs.writeFileSync(output, Object.entries(fields).map(([key, value]) => `${key}: "${value}"`).join('\n') + '\n', {mode: 0o600});
  console.log(`Configuration generated. JWT expires at ${new Date(expiresAt * 1000).toISOString()}.`);
  console.log(process.argv.includes('--av') ? 'Video and audio enabled; raw reception disabled.' :
    process.argv.includes('--video') ? 'Video enabled; audio and raw reception disabled.' : 'All media flags are disabled for the first connection test.');
} catch (error) {
  // JSON parser errors may include input content; never print them.
  console.error(error instanceof SyntaxError ? 'Invalid JSON in local configuration.' :
    error.code ? 'Cannot read/write local configuration; check file paths and permissions.' : error.message);
  process.exitCode = 1;
}
