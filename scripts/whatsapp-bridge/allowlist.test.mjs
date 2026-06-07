import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';

import {
  expandWhatsAppIdentifiers,
  matchesAllowedUser,
  normalizeWhatsAppIdentifier,
  parseAllowedUsers,
  shouldBypassAllowlistForInboxMode,
} from './allowlist.js';

test('normalizeWhatsAppIdentifier strips jid syntax and plus prefix', () => {
  assert.equal(normalizeWhatsAppIdentifier('+19175395595@s.whatsapp.net'), '19175395595');
  assert.equal(normalizeWhatsAppIdentifier('267383306489914@lid'), '267383306489914');
  assert.equal(normalizeWhatsAppIdentifier('19175395595:12@s.whatsapp.net'), '19175395595');
});

test('expandWhatsAppIdentifiers resolves phone and lid aliases from session files', () => {
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    writeFileSync(path.join(sessionDir, 'lid-mapping-19175395595.json'), JSON.stringify('267383306489914'));
    writeFileSync(path.join(sessionDir, 'lid-mapping-267383306489914_reverse.json'), JSON.stringify('19175395595'));

    const aliases = expandWhatsAppIdentifiers('267383306489914@lid', sessionDir);
    assert.deepEqual([...aliases].sort(), ['19175395595', '267383306489914']);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('matchesAllowedUser accepts mapped lid sender when allowlist only contains phone number', () => {
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    writeFileSync(path.join(sessionDir, 'lid-mapping-19175395595.json'), JSON.stringify('267383306489914'));
    writeFileSync(path.join(sessionDir, 'lid-mapping-267383306489914_reverse.json'), JSON.stringify('19175395595'));

    const allowedUsers = parseAllowedUsers('+19175395595');
    assert.equal(matchesAllowedUser('267383306489914@lid', allowedUsers, sessionDir), true);
    assert.equal(matchesAllowedUser('188012763865257@lid', allowedUsers, sessionDir), false);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('matchesAllowedUser treats * as allow-all wildcard', () => {
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    const allowedUsers = parseAllowedUsers('*');
    assert.equal(matchesAllowedUser('19175395595@s.whatsapp.net', allowedUsers, sessionDir), true);
    assert.equal(matchesAllowedUser('267383306489914@lid', allowedUsers, sessionDir), true);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('matchesAllowedUser rejects everyone when allowlist is empty (#8389)', () => {
  // Regression guard: empty allowlist used to return true (allow-everyone),
  // which let any stranger DM the bridge and trigger a Python-side
  // pairing-code reply. Secure default is now "reject unless explicitly
  // configured"; operators who want an open bot must set `*`.
  const sessionDir = mkdtempSync(path.join(os.tmpdir(), 'hermes-wa-allowlist-'));

  try {
    const empty = parseAllowedUsers('');
    assert.equal(empty.size, 0);
    assert.equal(matchesAllowedUser('19175395595@s.whatsapp.net', empty, sessionDir), false);
    assert.equal(matchesAllowedUser('267383306489914@lid', empty, sessionDir), false);

    // Null/undefined allowlist (defensive) also rejects.
    assert.equal(matchesAllowedUser('19175395595@s.whatsapp.net', null, sessionDir), false);
    assert.equal(matchesAllowedUser('19175395595@s.whatsapp.net', undefined, sessionDir), false);
  } finally {
    rmSync(sessionDir, { recursive: true, force: true });
  }
});

test('shouldBypassAllowlistForInboxMode lets inbox triage see normal incoming messages', () => {
  assert.equal(
    shouldBypassAllowlistForInboxMode({ inboxMode: true, chatId: '12345@s.whatsapp.net', fromMe: false }),
    true,
  );
  assert.equal(
    shouldBypassAllowlistForInboxMode({ inboxMode: true, chatId: '99999@g.us', fromMe: false }),
    true,
  );
});

test('shouldBypassAllowlistForInboxMode does not bypass status broadcasts or non-inbox mode', () => {
  assert.equal(
    shouldBypassAllowlistForInboxMode({ inboxMode: true, chatId: 'status@broadcast', fromMe: false }),
    false,
  );
  assert.equal(
    shouldBypassAllowlistForInboxMode({ inboxMode: false, chatId: '12345@s.whatsapp.net', fromMe: false }),
    false,
  );
  assert.equal(
    shouldBypassAllowlistForInboxMode({ inboxMode: true, chatId: '12345@s.whatsapp.net', fromMe: true }),
    false,
  );
});
