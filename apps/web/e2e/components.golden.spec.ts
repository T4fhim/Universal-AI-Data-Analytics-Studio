// Golden screenshots of the list components in the dev gallery (/components.html): the ranked
// leaderboard and the log pane (phase-4 step 7). Same pinned Linux container and baselines as the
// chart goldens (see playwright.config.ts); a box is one component on synthetic sample rows, so a
// pixel diff is a change to the component or to the tokens it draws with, and nothing else.
import { expect, test } from '@playwright/test'

const BOXES = [
  { title: 'Ranked list (leaderboard)', file: 'ranked-list.png' },
  { title: 'Log pane (K8 with level colours)', file: 'log-pane.png' },
]

for (const { title, file } of BOXES) {
  test(title, async ({ page }) => {
    await page.goto('/components.html')
    const box = page.getByRole('region', { name: title, exact: true })
    await expect(box).toBeVisible()
    await page.evaluate(() => document.fonts.ready)
    // Park the pointer off the page so no hover style is showing.
    await page.mouse.move(0, 0)
    await expect(box).toHaveScreenshot(file)
  })
}
