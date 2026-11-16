import relatedList from './related-list.js';
// Reuse the long-relation fixture, then measure the actual available drawer space.
export default async function drawerRailWidth(page,base='http://127.0.0.1:5205') {
  await relatedList(page,base);
  for(const width of [1920,1280,1024,390]) {
    await page.setViewportSize({width,height:900});
    await page.locator('.dw-cols').waitFor();
    if(width>=1024) {
      const geometry=await page.evaluate(()=>{
        const box=selector=>document.querySelector(selector).getBoundingClientRect();
        const drawer=box('.drawer-dialog'),rail=box('.dw-rail'),main=box('.dw-main');
        return {rightGap:drawer.right-rail.right,mainWidth:main.width,railWidth:rail.width};
      });
      if(geometry.rightGap>32 || geometry.mainWidth>861 || geometry.railWidth<287)throw new Error('Unused rail space: '+JSON.stringify(geometry));
    }
    if(await page.locator('.drawer-dialog').evaluate(el=>el.scrollWidth>el.clientWidth+1))throw new Error('Drawer width overflow');
  }
}
