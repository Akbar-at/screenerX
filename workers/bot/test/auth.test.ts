import test from 'node:test';
import assert from 'node:assert/strict';
import {authorized, sameSecret} from '../src/auth';
test('Webhook authentication fails closed', () => {
  assert.equal(sameSecret('', ''), false);
  assert.equal(sameSecret('secret', 'secret'), true);
  assert.equal(sameSecret('secrex', 'secret'), false);
});

test('Every member of an explicitly enabled group is allowed, with no other chat opened', () => {
  const update={update_id:124,message:{text:'/stock PTSN',from:{id:99},chat:{id:-100777000123,type:'supergroup'}}};
  assert.equal(authorized(update,'7','7','-100777000123'),true);
  assert.equal(authorized({...update,message:{...update.message,chat:{id:-100123,type:'supergroup'}}},'7','7','-100777000123'),false);
  assert.equal(authorized({...update,message:{...update.message,chat:{id:-100777000123,type:'private'}}},'7','7','-100777000123'),false);
  assert.equal(authorized(update,'7','7',undefined),false);
});
test('Both user and chat must match the explicit allowlists', () => {
  const update = {update_id: 123, message: {text: '/stock BBNI', from: {id: 7}, chat: {id: -8}}};
  assert.equal(authorized(update, '7', '-8'), true);
  assert.equal(authorized(update, '7', ''), false);
  assert.equal(authorized(update, '9', '-8'), false);
  assert.equal(authorized({update_id: '123'}, '7', '-8'), false);
  assert.equal(authorized(null, '7', '-8'), false);
  assert.equal(authorized(update, undefined, '-8'), false);
  assert.equal(authorized(update, '7', undefined), false);
});
