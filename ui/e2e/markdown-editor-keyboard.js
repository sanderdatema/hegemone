// An isolated component fixture keeps keyboard checks independent of form layout.
export default async function markdownEditorKeyboard(page, base = 'http://127.0.0.1:5197') {
  await page.route('**/editor-keyboard-fixture?*', route => route.fulfill({contentType: 'text/html', body: `
    <input aria-label="Title"><div id="editor"></div><button id="submit">Submit</button>
    <script type="module">
      import {createClassComponent} from '/node_modules/.vite/deps/svelte_legacy.js';
      import MarkdownEditor from '/src/MarkdownEditor.svelte';
      import {setLocale} from '/src/lib/i18n.js';
      setLocale(new URLSearchParams(location.search).get('language'));
      window.submissions = 0; window.cancels = 0;
      const editor = createClassComponent({component: MarkdownEditor, target: document.querySelector('#editor'), props: {
        ariaLabel: 'Description', value: 'Draft text',
        oninput: e => editor.$set({value: e.currentTarget.value}),
        onsubmit: () => window.submissions++, oncancel: () => window.cancels++,
      }});
    </script>`}));
  for (const language of ['en', 'nl']) {
    await page.goto(`${base}/editor-keyboard-fixture?language=${language}`);
    await page.locator('textarea').waitFor();
    await page.getByLabel('Title').focus();
    await page.keyboard.press('Tab');
    if (!(await page.locator('textarea').evaluate(el => el === document.activeElement))) throw new Error('Title must lead directly to textarea');
    await page.locator('textarea').fill('Preserved draft');
    await page.keyboard.press('Tab');
    if (!(await page.locator('#submit').evaluate(el => el === document.activeElement))) throw new Error('Textarea must lead directly to submit');
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Alt+Shift+P');
    const preview = page.locator('.md-editor-preview');
    await preview.waitFor();
    if (!(await preview.evaluate(el => el === document.activeElement))) throw new Error('Preview must retain focus');
    if (!(await preview.textContent()).includes('Preserved draft')) throw new Error('Preview lost draft');
    await page.keyboard.press('Control+Enter');
    await page.keyboard.press('Escape');
    if (await page.evaluate(() => window.submissions !== 1 || window.cancels !== 1)) throw new Error('Preview keyboard actions failed');
    await page.keyboard.press('Alt+Shift+P');
    if (await page.locator('textarea').inputValue() !== 'Preserved draft') throw new Error('Mode switch lost draft');
    await page.keyboard.press('Meta+Enter');
    await page.keyboard.press('Escape');
    if (await page.evaluate(() => window.submissions !== 2 || window.cancels !== 2)) throw new Error('Editor keyboard actions failed');
    await page.getByRole('radio', {name: language === 'en' ? 'Preview' : 'Voorbeeld', exact:true}).click();
    await page.reload();
    await preview.waitFor();
    await page.getByLabel('Title').focus();
    await page.keyboard.press('Tab');
    if (!(await preview.evaluate(el => el === document.activeElement))) throw new Error('Saved preview is unreachable');
    await page.keyboard.press('Alt+Shift+P');
    await page.locator('textarea').waitFor();
    if (!(await page.locator('textarea').evaluate(el => el === document.activeElement))) throw new Error('Saved preview cannot return to editor');
    await page.evaluate(() => sessionStorage.removeItem('betonning-md-preview'));
  }
}
