import test from 'node:test';
import assert from 'node:assert/strict';
import {validArtifactKey} from '../src/artifacts';

test('Daily digest media can be archived before Telegram delivery', () => {
  for (const name of ['top10-2026-10-14.png','daily-2026-10-14.pdf','BMRI-2026-10-14-chart.png']) {
    assert.equal(validArtifactKey('0123456789abcdef/'+name),true,name);
  }
  for (const name of ['../daily-2026-10-14.pdf','0123456789abcdef/../../secrets.pdf','0123456789abcdef/daily-2026-10-14.exe']) {
    assert.equal(validArtifactKey(name),false,name);
  }
});
