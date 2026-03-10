import { type Page, type Locator, expect } from '@playwright/test';

export class ProductListPage {
  readonly page: Page;
  readonly searchInput: Locator;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.searchInput = page.locator('input[placeholder="Search by title"]');
    this.heading = page.locator('h1', { hasText: 'Products' });
  }

  async goto() {
    await this.page.goto('/products');
    await expect(this.heading).toBeVisible();
  }

  async search(term: string) {
    await this.searchInput.fill(term);
  }

  async clearSearch() {
    await this.searchInput.fill('');
  }

  /** Returns all visible product cards. */
  getProductCards(): Locator {
    return this.page.locator('.grid > div > a > div');
  }

  /** Returns pagination buttons (numbered). */
  getPageButtons(): Locator {
    return this.page.locator('button').filter({ hasText: /^\d+$/ });
  }

  async clickProduct(title: string) {
    await this.page.locator('h2', { hasText: title }).first().click();
  }

  async clickPageButton(pageNumber: number) {
    await this.getPageButtons().filter({ hasText: String(pageNumber) }).click();
  }
}
