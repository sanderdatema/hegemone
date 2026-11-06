<script>
  import { locale, setLocale, t } from './lib/i18n.js';
</script>
<div class="language-picker" aria-label={$t('language.label')}>
  <button type="button" aria-pressed={$locale === 'en'} onclick={() => setLocale('en')}>English</button>
  <button type="button" aria-pressed={$locale === 'nl'} onclick={() => setLocale('nl')}>Nederlands</button>
</div>
<style>
  .language-picker { display: flex; gap: 8px; margin: 12px 0; }
  button[aria-pressed="true"] { color: var(--accent); font-weight: 700; }
</style>
