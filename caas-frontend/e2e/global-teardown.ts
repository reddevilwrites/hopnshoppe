import * as fs from 'fs';
import * as path from 'path';

const ACCOUNTS_FILE = path.join(__dirname, '.test-accounts.json');
const USER_SERVICE_URL = 'http://localhost:8084';
const AUTH_SERVICE_URL = 'http://localhost:8081';

/**
 * Playwright global teardown — runs once after all tests.
 *
 * Reads the list of test accounts created during the run from
 * e2e/.test-accounts.json and deletes them from both:
 * - user-service:  DELETE /internal/users/{email}
 * - auth-service:  DELETE /internal/credentials/{email}
 *
 * 404 responses are ignored (account may have already been deleted).
 */
export default async function globalTeardown() {
  if (!fs.existsSync(ACCOUNTS_FILE)) return;

  const emails: string[] = JSON.parse(fs.readFileSync(ACCOUNTS_FILE, 'utf8'));

  for (const email of emails) {
    const encoded = encodeURIComponent(email);
    await fetch(`${USER_SERVICE_URL}/internal/users/${encoded}`, { method: 'DELETE' }).catch(() => {});
    await fetch(`${AUTH_SERVICE_URL}/internal/credentials/${encoded}`, { method: 'DELETE' }).catch(() => {});
  }

  fs.unlinkSync(ACCOUNTS_FILE);
  console.log(`[teardown] Cleaned up ${emails.length} test account(s).`);
}
