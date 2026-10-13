export function sameSecret(actual: string, expected: string): boolean {
  if (!expected || actual.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= actual.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

export function authorized(update: unknown, users: string, chats: string): update is {update_id: number; message: {text: string}} {
  const u = update as any;
  const allowed = (list: string, value: unknown) => list.split(',').map(s => s.trim()).filter(Boolean).includes(String(value));
  return Number.isSafeInteger(u?.update_id) && typeof u?.message?.text === 'string' && u.message.text.length <= 4096
    && allowed(users, u.message.from?.id) && allowed(chats, u.message.chat?.id);
}
