import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { useMultiFileAuthState } from '@whiskeysockets/baileys';

const authModulePath = new URL(
  './node_modules/@whiskeysockets/baileys/lib/Utils/use-multi-file-auth-state.js',
  import.meta.url,
);

test('Baileys multi-file auth persists credentials through atomic replacement', async () => {
  const source = readFileSync(authModulePath, 'utf8');

  assert.match(source, /rename/, 'auth writes must import rename');
  assert.match(source, /const tmpPath = `\$\{filePath\}\.tmp`;/, 'auth writes must target a sibling temporary file');
  assert.match(source, /await writeFile\(tmpPath, JSON\.stringify\(data, BufferJSON\.replacer\)\);/, 'auth data must be written to the temporary file first');
  assert.match(source, /await rename\(tmpPath, filePath\);/, 'auth writes must atomically replace the destination');
  assert.doesNotMatch(
    source,
    /catch\s*\{[\s\S]*?writeFile\(filePath, JSON\.stringify\(data, BufferJSON\.replacer\)\);/,
    'a temporary-write or rename failure must preserve the existing credentials file rather than falling back to a direct write',
  );

  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-baileys-atomic-auth-'));
  try {
    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
    await saveCreds();

    const creds = JSON.parse(readFileSync(path.join(sessionDir, 'creds.json'), 'utf8'));
    assert.ok(creds.noiseKey, 'persisted credentials retain a noise key');
    assert.deepEqual(
      readdirSync(sessionDir).filter((entry) => entry.endsWith('.tmp')),
      [],
      'a successful save leaves no temporary auth files',
    );
    assert.equal(state.creds.noiseKey.private.length > 0, true);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});
