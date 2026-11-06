// Afleverstatus is geen netwerkresultaat totdat de dispatcher delivered boekt.
export function webhookTestState(delivery) {
  if (!delivery) return null;
  if (delivery.status === 'pending') return delivery.attempts > 0 ? 'retrying' : 'queued';
  return ['delivered', 'failed', 'cancelled'].includes(delivery.status) ? delivery.status : 'unknown';
}
export function canTestWebhook(user) {
  return user?.kind === 'agent' && user.active === true && !user.is_virtual && user.has_webhook === true;
}
