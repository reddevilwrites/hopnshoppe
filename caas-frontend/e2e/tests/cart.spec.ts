import { test, expect } from '@playwright/test';
import { CartPage } from '../pages/CartPage';
import { ProductDetailPage } from '../pages/ProductDetailPage';
import { LoginPage } from '../pages/LoginPage';
import { SignupPage } from '../pages/SignupPage';
import { createTestEmail, registerForCleanup } from '../fixtures/testAccounts';

/** SKU known to exist in the mocked catalog for cart tests. */
const TEST_SKU = 'SKU-TEST-001';
const MOCK_PRODUCT = { sku: TEST_SKU, title: 'Test Product', description: 'For testing', price: 9.99, availability: true, category: 'Test', imagePath: '' };

async function signupAndLogin(page: import('@playwright/test').Page, email: string) {
  const signup = new SignupPage(page);
  await signup.goto();
  await signup.signup({ email, firstName: 'Cart', lastName: 'Tester', password: 'Password123' });
  await signup.expectSuccess();

  const login = new LoginPage(page);
  await login.goto();
  await login.login(email, 'Password123');
  await login.expectRedirectToProducts();
}

test.describe('Cart management', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the single-product endpoint so cart enrichment (catalog-service) works
    await page.route(`/api/products/${TEST_SKU}`, (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_PRODUCT) });
    });
    // Mock the product list so the ProductDetail page loads
    await page.route('/api/products', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([MOCK_PRODUCT]) });
    });
    // Mock the cart enrichment response from GET /api/cart (cart items will have product info)
    // This ensures catalog-service data appears even without a real AEM CMS
    await page.route('/api/cart', (route, request) => {
      if (request.method() === 'GET') {
        // Let the real cart-service respond — we only mock catalog enrichment above
        route.continue();
      } else {
        route.continue();
      }
    });
  });

  test('add item to cart — cart badge updates', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    const detail = new ProductDetailPage(page);
    await detail.goto(TEST_SKU);
    await detail.addToCart();
    await detail.expectStatus('Added to cart');

    // Cart badge should show ≥ 1
    await expect(page.locator('span.bg-red-500')).toBeVisible();
  });

  test('view cart — added item appears', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    // Add item
    const detail = new ProductDetailPage(page);
    await detail.goto(TEST_SKU);
    await detail.addToCart();

    // View cart
    const cart = new CartPage(page);
    await cart.goto();
    await expect(cart.getItems()).toHaveCount(1);
  });

  test('increment quantity', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    // Add item
    const detail = new ProductDetailPage(page);
    await detail.goto(TEST_SKU);
    await detail.addToCart();

    const cart = new CartPage(page);
    await cart.goto();
    await cart.incrementItem(TEST_SKU);

    // Wait for quantity to update
    const qty = cart.getQuantityFor(TEST_SKU);
    await expect(qty).toContainText('2');
  });

  test('decrement to 1 then remove', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    // Add item and increment to qty 2
    const detail = new ProductDetailPage(page);
    await detail.goto(TEST_SKU);
    await detail.addToCart();

    const cart = new CartPage(page);
    await cart.goto();
    await cart.incrementItem(TEST_SKU);

    // Decrement back to 1
    await cart.decrementItem(TEST_SKU);
    await expect(cart.getQuantityFor(TEST_SKU)).toContainText('1');

    // Decrement again → item removed
    await cart.decrementItem(TEST_SKU);
    await cart.expectEmpty();
  });

  test('remove item directly → cart empty', async ({ page }) => {
    const email = createTestEmail();
    registerForCleanup(email);
    await signupAndLogin(page, email);

    const detail = new ProductDetailPage(page);
    await detail.goto(TEST_SKU);
    await detail.addToCart();

    const cart = new CartPage(page);
    await cart.goto();
    await cart.removeItem(TEST_SKU);
    await cart.expectEmpty();
  });

  test('add to cart unauthenticated — login prompt shown', async ({ page }) => {
    // No session
    await page.evaluate(() => sessionStorage.clear());

    const detail = new ProductDetailPage(page);
    await detail.goto(TEST_SKU);
    await detail.addToCart();
    await detail.expectStatus('Please log in');
  });

  test('cart page with cleared token — redirects to /login', async ({ page }) => {
    // Navigate to cart without token
    await page.evaluate(() => sessionStorage.clear());
    await page.goto('/cart');
    await expect(page).toHaveURL(/\/login/);
  });
});
